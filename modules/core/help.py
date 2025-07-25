import re
from html import escape

from jinja2 import FileSystemLoader, Environment

from core.builtins.bot import Bot
from core.builtins.message.internal import I18NContext, Plain
from core.builtins.parser.command import CommandParser
from core.component import module
from core.config import Config
from core.constants.default import donate_url_default, help_url_default, help_page_url_default
from core.constants.path import templates_path
from core.loader import ModulesManager, current_unloaded_modules, err_modules
from core.logger import Logger
from core.utils.cache import random_cache_path
from core.utils.image import cb64imglst
from core.web_render import web_render, ElementScreenshotOptions

env = Environment(loader=FileSystemLoader(templates_path), autoescape=True, enable_async=True)
help_url = Config("help_url", help_url_default)
donate_url = Config("donate_url", donate_url_default)
use_font_mirror = Config("use_font_mirror", False, bool)

hlp = module("help", base=True, doc=True)


@hlp.command("<module> [--legacy] {{I18N:core.help.help.detail}}",
             options_desc={"--legacy": "{I18N:help.option.legacy}"})
async def _(msg: Bot.MessageSession, module: str):
    is_base_superuser = msg.session_info.sender_id in Bot.base_superuser_list
    is_superuser = msg.check_super_user()
    module_list = ModulesManager.return_modules_list(
        target_from=msg.session_info.target_from, client_name=msg.session_info.client_name)
    alias = ModulesManager.modules_aliases

    if msg.parsed_msg:
        mdocs = []
        malias = []

        help_name = alias[module].split()[0] if module in alias else module.split()[0]
        if help_name in current_unloaded_modules:
            await msg.finish(I18NContext("parser.module.unloaded", module=help_name))
        elif help_name in err_modules:
            await msg.finish(I18NContext("error.module.unloaded", module=help_name))
        elif help_name in module_list:
            module_ = module_list[help_name]

            if module_.desc:
                desc = msg.session_info.locale.t_str(module_.desc)
                mdocs.append(desc)

            help_ = CommandParser(module_, msg=msg, bind_prefix=module_.bind_prefix,
                                  command_prefixes=msg.session_info.prefixes, is_superuser=is_superuser)

            if help_.args:
                mdocs.append(help_.return_formatted_help_doc())

            regex_list = module_.regex_list.get(
                msg.session_info.target_from,
                show_required_superuser=is_superuser,
                show_required_base_superuser=is_base_superuser)

            devs_msg = ""
            if (module_.required_superuser and not is_superuser) or \
                    (module_.required_base_superuser and not is_base_superuser):
                pass
            elif module_.rss and not msg.session_info.support_rss:
                pass
            else:
                if regex_list:
                    mdocs.append(str(I18NContext("core.help.regex.note")))
                    for regex in regex_list:
                        pattern = None
                        if isinstance(regex.pattern, str):
                            pattern = regex.pattern
                        elif isinstance(regex.pattern, re.Pattern):
                            pattern = regex.pattern.pattern
                        if pattern:
                            rdesc = regex.desc
                            if rdesc:
                                rdesc = msg.session_info.locale.t_str(rdesc)
                                mdocs.append(
                                    f"{pattern} {str(I18NContext("I18N:core.message.help.regex.detail", msg=rdesc))}")
                            else:
                                mdocs.append(
                                    f"{pattern} {str(I18NContext("I18N:core.message.help.regex.no_information"))}")

                if module_.alias:
                    for a in module_.alias:
                        malias.append(f"{a} -> {module_.alias[a]}")
                if module_.developers and not module_.base:
                    devs_msg = str(I18NContext("core.help.author")) + \
                        "{I18N:message.delimiter}".join(module_.developers)
                else:
                    devs_msg = ""

            if module_.doc:
                if help_page_url := Config("help_page_url", help_page_url_default, cfg_type=str):
                    wiki_msg = str(
                        I18NContext(
                            "core.message.help.helpdoc.address",
                            url=help_page_url.replace(
                                "${module}",
                                help_name)))
                elif help_url:
                    wiki_msg = str(I18NContext("core.message.help.helpdoc.address", url=help_url + help_name))
                else:
                    wiki_msg = ""
            else:
                wiki_msg = ""

            if not msg.parsed_msg.get("--legacy",
                                      False) and msg.session_info.support_image and Bot.Info.web_render_status:

                if (module_.required_superuser and not is_superuser) or \
                        (module_.required_base_superuser and not is_base_superuser):
                    pass
                elif module_.rss and not msg.session_info.support_rss:
                    pass
                elif any(
                        (module_.alias, module_.desc, module_.developers, help_.return_formatted_help_doc(), regex_list)):
                    try:
                        html_content = await env.get_template("help_doc.html").render_async(
                            locale=msg.session_info.locale,
                            module=module_,
                            help=help_,
                            help_name=help_name,
                            regex_list=regex_list,
                            escape=escape,
                            isinstance=isinstance,
                            str=str,
                            repattern=re.Pattern,
                            use_font_mirror=use_font_mirror)

                        # fname = f"{random_cache_path()}.html"
                        # with open(fname, "w", encoding="utf-8") as fi:
                        #     fi.write(html_content)

                        images = await web_render.element_screenshot(
                            ElementScreenshotOptions(content=html_content, element=[".botbox"]))
                        await msg.finish(cb64imglst(images, bot_img=True) + [Plain(wiki_msg.strip())])
                    except Exception:
                        Logger.exception()

                if wiki_msg:
                    await msg.finish(wiki_msg.strip())
                else:
                    await msg.finish(I18NContext("core.help.info.none"))

            doc_msg = mdocs + [devs_msg, wiki_msg]
            if doc_msg:
                await msg.finish(doc_msg)
            else:
                await msg.finish(I18NContext("core.help.info.none"))
        else:
            await msg.finish(I18NContext("core.message.help.not_found"))


@hlp.command()
@hlp.command("[--legacy] {{I18N:core.help.help}}",
             options_desc={"--legacy": "{I18N:help.option.legacy}"})
async def _(msg: Bot.MessageSession):
    legacy_help = True
    if not msg.parsed_msg and msg.session_info.support_image:
        imgs = await help_generator(msg)
        if imgs:
            legacy_help = False

            help_msg_list = [I18NContext("core.message.help.all_modules",
                                         prefix=msg.session_info.prefixes[0])]
            if help_url:
                help_msg_list.append(I18NContext("core.message.help.document", url=help_url))
            if donate_url:
                help_msg_list.append(I18NContext("core.message.help.donate", url=donate_url))
            await msg.finish(imgs + help_msg_list)
    if legacy_help:
        is_base_superuser = msg.session_info.sender_id in Bot.base_superuser_list
        is_superuser = msg.check_super_user()
        module_list = ModulesManager.return_modules_list(
            target_from=msg.session_info.target_from, client_name=msg.session_info.client_name)
        target_enabled_list = msg.session_info.enabled_modules
        help_msg = [I18NContext("core.message.help.legacy.base")]
        essential = []
        for x in module_list:
            if module_list[x].base and not module_list[x].hidden or \
                    not is_superuser and module_list[x].required_superuser or \
                    not is_base_superuser and module_list[x].required_base_superuser:
                essential.append(module_list[x].bind_prefix)
        help_msg.append(Plain(" | ".join(essential)))
        module_ = []
        for x in module_list:
            if x in target_enabled_list and not module_list[x].hidden or \
                    not is_superuser and module_list[x].required_superuser or \
                    not is_base_superuser and module_list[x].required_base_superuser:
                module_.append(x)
        if module_:
            help_msg.append(I18NContext("core.message.help.legacy.external"))
            help_msg.append(Plain(" | ".join(module_)))
        help_msg.append(I18NContext("core.message.help.detail", prefix=msg.session_info.prefixes[0]))
        help_msg.append(I18NContext("core.message.help.all_modules", prefix=msg.session_info.prefixes[0]))
        if help_url:
            help_msg.append(I18NContext("core.message.help.document", url=help_url))
        if donate_url:
            help_msg.append(I18NContext("core.message.help.donate", url=donate_url))
        await msg.finish(help_msg)


async def modules_list_help(msg: Bot.MessageSession, legacy):
    legacy_help = True
    if msg.session_info.support_image and not legacy:
        imgs = await help_generator(msg, show_disabled_modules=True, show_base_modules=False, show_dev_modules=False)
        if imgs:
            legacy_help = False
            help_msg = []
            if help_url:
                help_msg.append(I18NContext(
                    "core.message.help.document", url=help_url))
            await msg.finish(imgs + help_msg)
    if legacy_help:
        module_list = ModulesManager.return_modules_list(
            target_from=msg.session_info.target_from, client_name=msg.session_info.client_name)
        module_ = []
        for x in module_list:
            if x[0] == "_":
                continue
            if module_list[x].base or module_list[x].hidden or \
                    module_list[x].required_superuser or module_list[x].required_base_superuser:
                continue
            module_.append(module_list[x].bind_prefix)
        if module_:
            help_msg = [I18NContext("core.message.help.legacy.availables"), Plain(" | ".join(module_))]
        else:
            help_msg = [I18NContext("core.message.help.legacy.availables.none")]
        help_msg.append(I18NContext("core.message.help.detail", prefix=msg.session_info.prefixes[0]))
        if help_url:
            help_msg.append(I18NContext("core.message.help.document", url=help_url))
        await msg.finish(help_msg)


async def help_generator(msg: Bot.MessageSession,
                         show_base_modules: bool = True,
                         show_disabled_modules: bool = False,
                         show_dev_modules: bool = True,
                         use_local: bool = True):
    is_base_superuser = msg.session_info.sender_id in Bot.base_superuser_list
    is_superuser = msg.check_super_user()
    module_list = ModulesManager.return_modules_list(
        target_from=msg.session_info.target_from, client_name=msg.session_info.client_name)
    target_enabled_list = msg.session_info.enabled_modules

    dev_module_list = []
    essential = {}
    module_ = {}

    for key, value in module_list.items():
        if value.hidden:
            continue
        if value.rss and not msg.session_info.support_rss:
            continue
        if not is_superuser and value.required_superuser or \
                not is_base_superuser and value.required_base_superuser:
            continue

        if value.base:
            essential[key] = value
        else:
            module_[key] = value

        if value.required_superuser or value.required_base_superuser:
            dev_module_list.append(key)

    if not show_disabled_modules:
        module_ = {k: v for k, v in module_.items() if k in target_enabled_list or k in dev_module_list}

    if show_base_modules:
        module_list = {**essential, **module_}
    else:
        module_list = module_

    if not show_dev_modules:
        module_list = {k: v for k, v in module_.items() if k not in dev_module_list}

    html_content = await env.get_template("module_list.html").render_async(
        msg=msg,
        locale=msg.session_info.locale,
        CommandParser=CommandParser,
        is_base_superuser=is_base_superuser,
        is_superuser=is_superuser,
        len=len,
        module_list=module_list,
        show_disabled_modules=show_disabled_modules,
        target_enabled_list=target_enabled_list,
        use_font_mirror=use_font_mirror)
    fname = f"{random_cache_path()}.html"
    with open(fname, "w", encoding="utf-8") as fi:
        fi.write(html_content)

    images = await web_render.element_screenshot(ElementScreenshotOptions(content=html_content, element=[".botbox"]))
    if images:
        return cb64imglst(images, bot_img=True)
    return None
