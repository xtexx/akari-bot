import inspect
import re
import traceback
from datetime import datetime
from string import Template
from typing import TYPE_CHECKING

from core.builtins.message.chain import MessageChain, match_kecode
from core.builtins.message.internal import Plain, I18NContext
from core.builtins.parser.command import CommandParser
from core.builtins.session.lock import ExecutionLockList
from core.builtins.session.tasks import SessionTaskManager
from core.config import Config
from core.constants.default import bug_report_url_default, ignored_sender_default
from core.constants.exceptions import AbuseWarning, FinishedException, InvalidCommandFormatError, \
    InvalidHelpDocTypeError, \
    WaitCancelException, NoReportException, SendMessageFailed
from core.constants.info import Info
from core.database.models import AnalyticsData
from core.exports import exports
from core.loader import ModulesManager, current_unloaded_modules, err_modules
from core.logger import Logger
from core.tos import _abuse_warn_target
from core.types import Module, Param
from core.types.module.component_meta import CommandMeta
from core.utils.message import remove_duplicate_space

if TYPE_CHECKING:
    from core.builtins.bot import Bot

ignored_sender = Config("ignored_sender", ignored_sender_default)

enable_tos = Config("enable_tos", True)
enable_analytics = Config("enable_analytics", False)
report_targets = Config("report_targets", [])
TOS_TEMPBAN_TIME = Config("tos_temp_ban_time", 300) if Config("tos_temp_ban_time", 300) > 0 else 300
bug_report_url = Config("bug_report_url", bug_report_url_default)

counter_same = {}  # 命令使用次数计数（重复使用单一命令）
counter_all = {}  # 命令使用次数计数（使用所有命令）

temp_ban_counter = {}  # 临时封禁计数
cooldown_counter = {}  # 冷却计数

match_hash_cache = {}


async def check_temp_ban(target):
    is_temp_banned = temp_ban_counter.get(target)
    if is_temp_banned:
        ban_time = datetime.now().timestamp() - is_temp_banned["ts"]
        ban_time_remain = int(TOS_TEMPBAN_TIME - ban_time)
        if ban_time_remain > 0:
            return ban_time_remain
    return False


async def remove_temp_ban(target):
    if await check_temp_ban(target):
        del temp_ban_counter[target]


async def parser(msg: "Bot.MessageSession"):
    """
    接收消息必经的预处理器。

    :param msg: 从监听器接收到的dict，该dict将会经过此预处理器传入下游。
    """
    await msg.session_info.refresh_info()
    identify_str = f"[{msg.session_info.sender_id} ({msg.session_info.target_id})]"
    # Logger.info(f"{identify_str} -> [Bot]: {display}")

    if msg.session_info.sender_id in ignored_sender:
        return

    try:
        await SessionTaskManager.check(msg)
        modules = ModulesManager.return_modules_list(msg.session_info.target_from, msg.session_info.client_name)

        msg.trigger_msg = remove_duplicate_space(msg.as_display())  # 将消息转换为一般显示形式
        if len(msg.trigger_msg) == 0:
            return
        if (
            msg.session_info.sender_info.blocked and not msg.session_info.sender_info.trusted and not msg.session_info.sender_info.superuser) or (
            msg.session_info.sender_id in msg.session_info.target_info.target_data.get("ban",
                                                                                       []) and not msg.session_info.superuser):
            return

        disable_prefix, in_prefix_list, display_prefix = _get_prefixes(msg)

        if in_prefix_list or disable_prefix:  # 检查消息前缀
            Logger.info(
                f"{identify_str} -> [Bot]: {msg.trigger_msg}")
            command_first_word = await _process_command(msg, modules, disable_prefix, in_prefix_list, display_prefix)

            if command_first_word:
                if not ExecutionLockList.check(msg):  # 加锁
                    ExecutionLockList.add(msg)
                else:
                    await msg.send_message(I18NContext("parser.command.running.prompt"))
                    return

            if msg.session_info.muted and command_first_word != "mute":
                return

            if command_first_word in modules:  # 检查触发命令是否在模块列表中
                await _execute_module(msg, modules, command_first_word, identify_str)
            if command_first_word in current_unloaded_modules:
                await msg.send_message(I18NContext("parser.module.unloaded", module=command_first_word))
            elif command_first_word in err_modules:
                await msg.send_message(I18NContext("error.module.unloaded", module=command_first_word))

            return msg
        if msg.session_info.muted:
            return
        if msg.session_info.running_mention:
            if msg.trigger_msg.lower().find(msg.session_info.bot_name.lower()) != -1:
                if ExecutionLockList.check(msg):
                    return await msg.send_message(I18NContext("parser.command.running.prompt2"))

        await _execute_regex(msg, modules, identify_str)
        return msg

    except WaitCancelException:  # 出现于等待被取消的情况
        Logger.warning("Waiting task cancelled by user.")

    except Exception:
        Logger.exception()
    finally:
        await msg.end_typing()
        ExecutionLockList.remove(msg)


def _transform_alias(msg, command: str):
    aliases = dict(msg.session_info.target_info.target_data.get("command_alias", {}).items())
    command_split = msg.trigger_msg.split(" ")  # 切割消息
    for pattern, replacement in aliases.items():
        if re.search(r"\${[^}]*}", pattern):
            # 使用正则表达式匹配并分隔多个连在一起的占位符
            pattern = re.sub(r"(\$\{\w+})(?=\$\{\w+})", r"\1 ", pattern)
            # 匹配占位符
            pattern_placeholders = re.findall(r"\$\{([^{}$]+)}", pattern)

            regex_pattern = re.escape(pattern)
            for placeholder in pattern_placeholders:
                regex_pattern = regex_pattern.replace(re.escape(f"${{{placeholder}}}"), r"(\S+)")  # 匹配非空格字符

            match = re.match(regex_pattern, command)
            if match:
                groups = match.groups()
                placeholder_dict = {placeholder: groups[i] for i,
                                    placeholder in enumerate(pattern_placeholders) if i < len(groups)}
                result = Template(replacement).safe_substitute(placeholder_dict)

                Logger.debug(msg.session_info.prefixes[0] + result)
                return msg.session_info.prefixes[0] + result
        elif command_split[0] == pattern:
            # 旧语法兼容
            command_split[0] = msg.session_info.prefixes[0] + replacement  # 将自定义别名替换为命令
            Logger.debug(" ".join(command_split))
            return " ".join(command_split)  # 重新连接消息
        else:
            pass

    return command


def _get_prefixes(msg: "Bot.MessageSession"):
    if msg.session_info.target_info.target_data.get("command_alias"):
        msg.trigger_msg = _transform_alias(msg, msg.trigger_msg)  # 将自定义别名替换为命令

    disable_prefix = False
    if msg.session_info.prefixes:  # 如果上游指定了命令前缀，则使用指定的命令前缀
        if "" in msg.session_info.prefixes:
            disable_prefix = True
    display_prefix = ""
    in_prefix_list = False
    for cp in msg.session_info.prefixes:  # 判断是否在命令前缀列表中
        if msg.trigger_msg.startswith(cp):
            display_prefix = cp
            in_prefix_list = True
            break
    if in_prefix_list or disable_prefix:  # 检查消息前缀
        if len(msg.trigger_msg) <= 1 or msg.trigger_msg[:2] == "~~":  # 排除 ~~xxx~~ 的情况
            return False, False, ""
        if in_prefix_list:  # 如果在命令前缀列表中，则将此命令前缀移动到列表首位
            msg.session_info.prefixes.remove(display_prefix)
            msg.session_info.prefixes.insert(0, display_prefix)

    return disable_prefix, in_prefix_list, display_prefix


async def _process_command(msg: "Bot.MessageSession", modules, disable_prefix, in_prefix_list, display_prefix):
    if disable_prefix and not in_prefix_list:
        command = msg.trigger_msg
    else:
        command = msg.trigger_msg[len(display_prefix):]
    command = command.strip()
    not_alias = False
    cm = ""
    for moduleName in modules:
        if command.startswith(moduleName):  # 判断此命令是否匹配一个实际的模块
            not_alias = True
            cm = moduleName
            break
    if not not_alias:
        for um in current_unloaded_modules:
            if command.startswith(um):
                not_alias = True
                cm = um
                break
    if not not_alias:
        for em in err_modules:
            if command.startswith(em):
                not_alias = True
                cm = em
                break
    alias_list = []
    for alias in ModulesManager.modules_aliases:
        if not not_alias:  # 如果没有匹配到模块，则判断是否匹配命令别名
            if command.startswith(alias) and not command.startswith(ModulesManager.modules_aliases[alias]):
                alias_list.append(alias)
        else:  # 如果是模块，则判断是否有基于此模块前缀的别名
            if alias.startswith(cm) and command.startswith(alias):
                alias_list.append(alias)
    if alias_list:
        max_ = max(alias_list, key=len)
        command = command.replace(max_, ModulesManager.modules_aliases[str(max_)], 1)

    command_split: list = command.split(" ")  # 切割消息
    msg.trigger_msg = command  # 触发该命令的消息，去除消息前缀
    command_first_word = command_split[0].lower()

    return command_first_word


async def _execute_module(msg: "Bot.MessageSession", modules, command_first_word, identify_str):
    time_start = datetime.now()
    bot: "Bot" = exports["Bot"]
    try:
        await _check_target_cooldown(msg)
        if enable_tos:
            await _check_temp_ban(msg)

        module: Module = modules[command_first_word]
        if not module.command_list.set:  # 如果没有可用的命令，则展示模块简介
            if module.desc:
                desc = [I18NContext("parser.module.desc", desc=msg.session_info.locale.t_str(module.desc))]
                if command_first_word not in msg.session_info.enabled_modules:
                    desc.append(
                        I18NContext(
                            "parser.module.disabled.prompt",
                            module=command_first_word,
                            prefix=msg.session_info.prefixes[0]))
                await msg.send_message(desc)
            else:
                await msg.send_message(I18NContext("error.module.unbound", module=command_first_word))
            return

        if module.required_base_superuser:
            if msg.session_info.sender_id not in bot.base_superuser_list:
                await msg.send_message(I18NContext("parser.superuser.permission.denied"))
                return
        elif module.required_superuser:
            if not msg.check_super_user():
                await msg.send_message(I18NContext("parser.superuser.permission.denied"))
                return
        elif not module.base:
            if command_first_word not in msg.session_info.enabled_modules and msg.session_info.require_enable_modules:  # 若未开启
                await msg.send_message(I18NContext("parser.module.disabled.prompt", module=command_first_word,
                                                   prefix=msg.session_info.prefixes[0]))
                if await msg.check_permission():
                    if await msg.wait_confirm(I18NContext("parser.module.disabled.to_enable")):
                        await msg.session_info.target_info.config_module(command_first_word)
                        await msg.send_message(
                            I18NContext("core.message.module.enable.success", module=command_first_word))
                    else:
                        return
                else:
                    return
        elif module.required_admin:
            if not await msg.check_permission():
                await msg.send_message(I18NContext("parser.admin.module.permission.denied", module=command_first_word))
                return

        if not module.base:
            if enable_tos:
                await _tos_msg_counter(msg, msg.trigger_msg)
            else:
                Logger.debug("Tos is disabled, check the configuration if it is not work as expected.")

        none_doc = True  # 检查模块绑定的命令是否有文档
        for func in module.command_list.get(msg.session_info.target_from):
            if func.help_doc:
                none_doc = False
        if not none_doc:  # 如果有，送入命令解析
            await _execute_submodule(msg, module, command_first_word)
        else:  # 如果没有，直接传入下游模块
            msg.parsed_msg = None
            for func in module.command_list.set:
                if not func.help_doc:
                    if not msg.session_info.sender_info.sender_data.get("disable_typing", False):
                        await msg.start_typing()
                        await func.function(msg)  # 将msg传入下游模块

                    else:
                        await func.function(msg)
                    raise FinishedException(msg.sent)  # if not using msg.finish
    except SendMessageFailed:
        await _process_send_message_failed(msg)

    except FinishedException as e:

        time_used = datetime.now() - time_start
        Logger.success(f"Successfully finished session from {identify_str}, returns: {str(e)}. "
                       f"Times take up: {str(time_used)}")
        Info.command_parsed += 1
        if enable_analytics:
            await AnalyticsData.create(target_id=msg.session_info.target_id,
                                       sender_id=msg.session_info.sender_id,
                                       command=msg.trigger_msg,
                                       module_name=command_first_word,
                                       module_type="normal")
    except AbuseWarning as e:
        await _process_tos_abuse_warning(msg, e)

    except NoReportException as e:
        await _process_noreport_exception(msg, e)

    except Exception as e:
        await _process_exception(msg, e)
    finally:
        await msg.end_typing()
        ExecutionLockList.remove(msg)


async def _execute_regex(msg: "Bot.MessageSession", modules, identify_str):
    bot: "Bot" = exports["Bot"]
    for m in modules:  # 遍历模块
        try:
            if m in msg.session_info.enabled_modules and modules[m].regex_list.set:  # 如果模块已启用
                regex_module: Module = modules[m]

                if regex_module.required_base_superuser:
                    if msg.session_info.sender_id not in bot.base_superuser_list:
                        continue
                elif regex_module.required_superuser:
                    if not msg.check_super_user():
                        continue
                elif regex_module.required_admin:
                    if not await msg.check_permission():
                        continue

                if not regex_module.load or \
                    msg.session_info.target_from in regex_module.exclude_from or \
                    msg.session_info.client_name in regex_module.exclude_from or \
                    ("*" not in regex_module.available_for and
                     msg.session_info.target_from not in regex_module.available_for and
                     msg.session_info.client_name not in regex_module.available_for):
                    continue

                for rfunc in regex_module.regex_list.set:  # 遍历正则模块的表达式
                    time_start = datetime.now()
                    matched = False
                    _typing = False
                    try:
                        matched_hash = 0
                        trigger_msg = msg.as_display(text_only=rfunc.text_only)
                        if rfunc.mode.upper() in ["M", "MATCH"]:
                            msg.matched_msg = re.match(rfunc.pattern, trigger_msg, flags=rfunc.flags)
                            if msg.matched_msg:
                                matched = True
                                matched_hash = hash(msg.matched_msg.groups())
                        elif rfunc.mode.upper() in ["A", "FINDALL"]:
                            msg.matched_msg = re.findall(rfunc.pattern, trigger_msg, flags=rfunc.flags)
                            msg.matched_msg = tuple(set(msg.matched_msg))
                            if msg.matched_msg:
                                matched = True
                                matched_hash = hash(msg.matched_msg)

                        if matched and regex_module.load and not (
                            msg.session_info.target_from in regex_module.exclude_from or
                            msg.session_info.client_name in regex_module.exclude_from or
                            ("*" not in regex_module.available_for and
                             msg.session_info.target_from not in regex_module.available_for and
                             msg.session_info.client_name not in regex_module.available_for)):  # 如果匹配成功

                            if rfunc.logging:
                                Logger.info(
                                    f"{identify_str} -> [Bot]: {msg.trigger_msg}")
                            Logger.debug("Matched hash:" + str(matched_hash))
                            if msg.session_info.target_id not in match_hash_cache:
                                match_hash_cache[msg.session_info.target_id] = {}
                            if rfunc.logging and matched_hash in match_hash_cache[msg.session_info.target_id] and \
                                    datetime.now().timestamp() - match_hash_cache[msg.session_info.target_id][
                                    matched_hash] < int(
                                    (msg.session_info.target_info.target_data.get("cooldown_time", 0)) or 3):
                                Logger.warning("Match loop detected, skipping...")
                                continue
                            match_hash_cache[msg.session_info.target_id][matched_hash] = datetime.now().timestamp()

                            if enable_tos and rfunc.show_typing:
                                await _check_temp_ban(msg)
                            if rfunc.show_typing:
                                await _check_target_cooldown(msg)
                            if rfunc.required_superuser:
                                if not msg.check_super_user():
                                    continue
                            elif rfunc.required_admin:
                                if not await msg.check_permission():
                                    continue

                            if not regex_module.base:
                                if enable_tos and rfunc.show_typing:
                                    await _tos_msg_counter(msg, msg.trigger_msg)
                                else:
                                    Logger.debug(
                                        "Tos is disabled, check the configuration if it is not work as expected.")

                            if not ExecutionLockList.check(msg):
                                ExecutionLockList.add(msg)
                            else:
                                return await msg.send_message(I18NContext("parser.command.running.prompt"))

                            if rfunc.show_typing and not msg.session_info.sender_info.sender_data.get(
                                    "disable_typing", False):
                                await msg.start_typing()
                                _typing = True
                                await rfunc.function(msg)  # 将msg传入下游模块

                            else:
                                await rfunc.function(msg)  # 将msg传入下游模块
                            raise FinishedException(msg.sent)  # if not using msg.finish
                    except FinishedException as e:
                        time_used = datetime.now() - time_start
                        if rfunc.logging:
                            Logger.success(
                                f"Successfully finished session from {identify_str}, returns: {str(e)}. "
                                f"Times take up: {time_used}")

                        Info.command_parsed += 1
                        if enable_analytics:
                            await AnalyticsData.create(target_id=msg.session_info.target_id,
                                                       sender_id=msg.session_info.sender_id,
                                                       command=msg.trigger_msg,
                                                       module_name=m,
                                                       module_type="regex")
                        continue

                    except NoReportException as e:
                        await _process_noreport_exception(msg, e)

                    except AbuseWarning as e:
                        await _process_tos_abuse_warning(msg, e)

                    except Exception as e:
                        await _process_exception(msg, e)
                    finally:
                        if _typing:
                            await msg.end_typing()
                            ExecutionLockList.remove(msg)

        except SendMessageFailed:
            await _process_send_message_failed(msg)
            continue


async def _check_target_cooldown(msg: "Bot.MessageSession"):
    cooldown_time = int(msg.session_info.target_info.target_data.get("cooldown_time", 0))
    neutralized = bool(await msg.check_native_permission() or await msg.check_permission() or msg.check_super_user())

    if cooldown_time and not neutralized:
        if cooldown_counter.get(msg.session_info.target_id, {}).get(msg.session_info.sender_id):
            time = datetime.now().timestamp() - \
                cooldown_counter[msg.session_info.target_id][msg.session_info.sender_id]["ts"]
            if time > cooldown_time:
                cooldown_counter[msg.session_info.target_id].update(
                    {msg.session_info.sender_id: {"ts": datetime.now().timestamp()}})
            else:
                await msg.finish(I18NContext("message.cooldown.manual", time=int(cooldown_time - time)))
        else:
            cooldown_counter[msg.session_info.target_id] = {
                msg.session_info.sender_id: {"ts": datetime.now().timestamp()}}


async def _check_temp_ban(msg: "Bot.MessageSession"):
    is_temp_banned = temp_ban_counter.get(msg.session_info.sender_id)
    if is_temp_banned:
        if msg.check_super_user():
            await remove_temp_ban(msg.session_info.sender_id)
            return None
        ban_time = datetime.now().timestamp() - is_temp_banned["ts"]
        if ban_time < TOS_TEMPBAN_TIME:
            if is_temp_banned["count"] < 2:
                is_temp_banned["count"] += 1
                await msg.finish(I18NContext("tos.message.tempbanned", ban_time=int(TOS_TEMPBAN_TIME - ban_time)))
            elif is_temp_banned["count"] <= 5:
                is_temp_banned["count"] += 1
                await msg.finish(
                    I18NContext("tos.message.tempbanned.warning", ban_time=int(TOS_TEMPBAN_TIME - ban_time)))
            else:
                raise AbuseWarning("{I18N:tos.message.reason.ignore}")


async def _tos_msg_counter(msg: "Bot.MessageSession", command: str):
    same = counter_same.get(msg.session_info.sender_id)
    if not same or datetime.now().timestamp() - same["ts"] > 300 or same["command"] != command:
        # 检查是否滥用（5分钟内重复使用同一命令10条）

        counter_same[msg.session_info.sender_id] = {"command": command, "count": 1,
                                                    "ts": datetime.now().timestamp()}
    else:
        same["count"] += 1
        if same["count"] > 10:
            raise AbuseWarning("{I18N:tos.message.reason.cooldown}")
    all_ = counter_all.get(msg.session_info.sender_id)
    if not all_ or datetime.now().timestamp() - all_["ts"] > 300:  # 检查是否滥用（5分钟内使用20条命令）
        counter_all[msg.session_info.sender_id] = {"count": 1,
                                                   "ts": datetime.now().timestamp()}
    else:
        all_["count"] += 1
        if all_["count"] > 20:
            raise AbuseWarning("{I18N:tos.message.reason.abuse}")


async def _execute_submodule(msg: "Bot.MessageSession", module, command_first_word):
    bot: "Bot" = exports["Bot"]
    try:
        command_parser = CommandParser(module, msg=msg, bind_prefix=command_first_word,
                                       command_prefixes=msg.session_info.prefixes)
        try:
            parsed_msg = command_parser.parse(msg.trigger_msg)  # 解析命令对应的子模块
            submodule: CommandMeta = parsed_msg[0]
            msg.parsed_msg = parsed_msg[1]  # 使用命令模板解析后的消息
            Logger.trace('Parsed message: ' + str(msg.parsed_msg))

            if submodule.required_base_superuser:
                if msg.session_info.sender_id not in bot.base_superuser_list:
                    await msg.send_message(I18NContext("parser.superuser.permission.denied"))
                    return
            elif submodule.required_superuser:
                if not msg.check_super_user():
                    await msg.send_message(I18NContext("parser.superuser.permission.denied"))
                    return
            elif submodule.required_admin:
                if not await msg.check_permission():
                    await msg.send_message(I18NContext("parser.admin.submodule.permission.denied"))
                    return

            if not submodule.load or \
                msg.session_info.target_from in submodule.exclude_from or \
                msg.session_info.client_name in submodule.exclude_from or \
                ("*" not in submodule.available_for and
                 msg.session_info.target_from not in submodule.available_for and
                 msg.session_info.client_name not in submodule.available_for):
                raise InvalidCommandFormatError

            kwargs = {}
            func_params = inspect.signature(submodule.function).parameters
            if len(func_params) > 1 and msg.parsed_msg:
                parsed_msg_ = msg.parsed_msg.copy()
                no_message_session = True
                for param_name, param_obj in func_params.items():
                    if param_obj.annotation == bot.MessageSession:
                        kwargs[param_name] = msg
                        no_message_session = False
                    elif isinstance(param_obj.annotation, Param):
                        if param_obj.annotation.name in parsed_msg_:
                            if isinstance(
                                    parsed_msg_[
                                        param_obj.annotation.name],
                                    param_obj.annotation.type):
                                kwargs[param_name] = parsed_msg_[param_obj.annotation.name]
                                del parsed_msg_[param_obj.annotation.name]
                            else:
                                Logger.warning(f"{param_obj.annotation.name} is not a {
                                    param_obj.annotation.type}")
                        else:
                            Logger.warning(f"{param_obj.annotation.name} is not in parsed_msg")
                    param_name_ = param_name

                    if (param_name__ := f"<{param_name}>") in parsed_msg_:
                        param_name_ = param_name__

                    if param_name_ in parsed_msg_:
                        kwargs[param_name] = parsed_msg_[param_name_]
                        try:
                            if param_obj.annotation == int:
                                kwargs[param_name] = int(parsed_msg_[param_name_])
                            elif param_obj.annotation == float:
                                kwargs[param_name] = float(parsed_msg_[param_name_])
                            elif param_obj.annotation == bool:
                                kwargs[param_name] = bool(parsed_msg_[param_name_])
                            del parsed_msg_[param_name_]
                        except (KeyError, ValueError):
                            raise InvalidCommandFormatError
                    else:
                        if param_name_ not in kwargs:
                            if param_obj.default is not inspect.Parameter.empty:
                                kwargs[param_name_] = param_obj.default
                            else:
                                kwargs[param_name_] = None
                if no_message_session:
                    Logger.warning(
                        f"{submodule.function.__name__} has no Bot.MessageSession parameter, did you forgot to add it?\n"
                        "Remember: MessageSession IS NOT Bot.MessageSession")
            else:
                kwargs[func_params[list(func_params.keys())[0]].name] = msg

            if not msg.session_info.target_info.target_data.get("disable_typing", False):
                await msg.start_typing()
                await parsed_msg[0].function(**kwargs)  # 将msg传入下游模块
            else:
                await parsed_msg[0].function(**kwargs)
            raise FinishedException(msg.sent)  # if not using msg.finish
        except InvalidCommandFormatError:
            await msg.send_message(I18NContext("parser.command.format.invalid",
                                               module=command_first_word,
                                               prefix=msg.session_info.prefixes[0]))
            """if msg.session_info.target_info.target_data.get("typo_check", True):  # 判断是否开启错字检查
                nmsg, command_first_word, command_split = await _typo_check(msg,
                                                                            display_prefix,
                                                                            modules,
                                                                            command_first_word,
                                                                            command_split)
                if nmsg is None:
                    return ExecutionLockList.remove(msg)
                msg = nmsg
                await _execute_submodule(msg, command_first_word, command_split)"""
            return
    except InvalidHelpDocTypeError:
        Logger.exception()
        await msg.send_message(I18NContext("error.module.helpdoc.invalid", module=command_first_word))
        return


async def _process_tos_abuse_warning(msg: "Bot.MessageSession", e: AbuseWarning):
    if enable_tos and Config("tos_warning_counts", 5) >= 1 and not msg.check_super_user():
        await _abuse_warn_target(msg, str(e))
        temp_ban_counter[msg.session_info.sender_id] = {"count": 1,
                                                        "ts": datetime.now().timestamp()}
    else:
        errmsgchain = MessageChain.assign(I18NContext("error.message.prompt"))
        errmsgchain.append(Plain(msg.session_info.locale.t_str(str(e))))
        errmsgchain.append(I18NContext("error.message.prompt.noreport"))
        await msg.send_message(errmsgchain)


async def _process_send_message_failed(msg: "Bot.MessageSession"):
    await msg.handle_error_signal()
    await msg.send_message(I18NContext("error.message.limited"))


async def _process_noreport_exception(msg: "Bot.MessageSession", e: NoReportException):
    Logger.exception()
    errmsgchain = MessageChain.assign(I18NContext("error.message.prompt"))
    err_msg = msg.session_info.locale.t_str(str(e))
    errmsgchain += match_kecode(err_msg)
    errmsgchain.append(I18NContext("error.message.prompt.noreport"))
    await msg.send_message(errmsgchain)


async def _process_exception(msg: "Bot.MessageSession", e: Exception):
    bot: "Bot" = exports["Bot"]
    tb = traceback.format_exc()
    Logger.error(tb)
    errmsgchain = MessageChain.assign(I18NContext("error.message.prompt"))
    err_msg = msg.session_info.locale.t_str(str(e))
    errmsgchain += match_kecode(err_msg)
    await msg.handle_error_signal()
    if "timeout" in err_msg.lower().replace(" ", ""):
        timeout = True
        errmsgchain.append(I18NContext("error.message.prompt.timeout"))
    else:
        timeout = False
        errmsgchain.append(I18NContext("error.message.prompt.report"))

    if bug_report_url:
        errmsgchain.append(I18NContext("error.message.prompt.address", url=bug_report_url))
    await msg.send_message(errmsgchain)

    if not timeout and report_targets:
        for target in report_targets:
            if f := await bot.fetch_target(target):
                await bot.send_direct_message(f, [I18NContext("error.message.report", module=msg.trigger_msg),
                                                  Plain(tb.strip(), disable_joke=True)],
                                              enable_parse_message=False, disable_secret_check=True)


"""async def typo_check(msg: MessageSession, display_prefix, modules, command_first_word, command_split):
    enabled_modules = []
    for m in msg.session_info.enabled_modules:
        if m in modules and isinstance(modules[m], Command):
            enabled_modules.append(m)
    match_close_module: list = difflib.get_close_matches(command_first_word, enabled_modules, 1, 0.6)
    if match_close_module:
        module = modules[match_close_module[0]]
        none_doc = True  # 检查模块绑定的命令是否有文档
        for func in module.match_list.get(msg.session_info.targetFrom):
            if func.help_doc is not None:
                none_doc = False
        len_command_split = len(command_split)
        if not none_doc and len_command_split > 1:
            get_submodules: List[CommandMeta] = module.match_list.get(msg.session_info.targetFrom)
            docs = {}  # 根据命令模板的空格数排序命令
            for func in get_submodules:
                help_doc: List[Template] = copy.deepcopy(func.help_doc)
                if not help_doc:
                    ...  # todo: ...此处应该有一个处理例外情况的逻辑

                for h_ in help_doc:
                    h_.args_ = [a for a in h_.args if isinstance(a, ArgumentPattern)]
                    if (len_args := len(h_.args)) not in docs:
                        docs[len_args] = [h_]
                    else:
                        docs[len_args].append(h_)

            if len_command_split - 1 > len(docs):  # 如果空格数远大于命令模板的空格数
                select_docs = docs[max(docs)]
            else:
                select_docs = docs[len_command_split - 1]  # 选择匹配的命令组
            match_close_command: list = difflib.get_close_matches(" ".join(command_split[1:]),
                                                                  templates_to_str(select_docs),
                                                                  1, 0.3)  # 进一步匹配命令
            if match_close_command:
                match_split = match_close_command[0]
                m_split_options = filter(None, re.split(r"(\\[.*?])", match_split))  # 切割可选参数
                old_command_split = command_split.copy()
                del old_command_split[0]
                new_command_split = [match_close_module[0]]
                for m_ in m_split_options:
                    if m_.startswith("["):  # 如果是可选参数
                        m_split = m_.split(" ")  # 切割可选参数中的空格（说明存在多个子必须参数）
                        if len(m_split) > 1:
                            match_close_options = difflib.get_close_matches(m_split[0][1:], old_command_split, 1,
                                                                            0.3)  # 进一步匹配可选参数
                            if match_close_options:
                                position = old_command_split.index(match_close_options[0])  # 定位可选参数的位置
                                new_command_split.append(m_split[0][1:])  # 将可选参数插入到新命令列表中
                                new_command_split += old_command_split[position + 1: position + len(m_split)]
                                del old_command_split[position: position + len(m_split)]  # 删除原命令列表中的可选参数
                        else:
                            if m_split[0][1] == "<":
                                new_command_split.append(old_command_split[0])
                                del old_command_split[0]
                            else:
                                new_command_split.append(m_split[0][1:-1])
                    else:
                        m__ = filter(None, m_.split(" "))  # 必须参数
                        for mm in m__:
                            if len(old_command_split) > 0:
                                if mm.startswith("<"):
                                    new_command_split.append(old_command_split[0])
                                    del old_command_split[0]
                                else:
                                    match_close_args = difflib.get_close_matches(old_command_split[0], [mm], 1,
                                                                                 0.5)  # 进一步匹配参数
                                    if match_close_args:
                                        new_command_split.append(mm)
                                        del old_command_split[0]
                                    else:
                                        new_command_split.append(old_command_split[0])
                                        del old_command_split[0]
                            else:
                                new_command_split.append(mm)
                new_command_display = " ".join(new_command_split)
                if new_command_display != msg.trigger_msg:
                    wait_confirm = await msg.waitConfirm(
                        f"你是否想要输入{display_prefix}{new_command_display}？")
                    if wait_confirm:
                        command_split = new_command_split
                        command_first_word = new_command_split[0]
                        msg.trigger_msg = " ".join(new_command_split)
                        return msg, command_first_word, command_split
            else:
                if len_command_split - 1 == 1:
                    new_command_display = f"{match_close_module[0]} {" ".join(command_split[1:])}"
                    if new_command_display != msg.trigger_msg:
                        wait_confirm = await msg.waitConfirm(
                            f"你是否想要输入{display_prefix}{new_command_display}？")
                        if wait_confirm:
                            command_split = [match_close_module[0]] + command_split[1:]
                            command_first_word = match_close_module[0]
                            msg.trigger_msg = " ".join(command_split)
                            return msg, command_first_word, command_split

        else:
            new_command_display = f"{match_close_module[0] + (" " + " ".join(command_split[1:]) if len(command_split) > 1 else "")}"
            if new_command_display != msg.trigger_msg:
                wait_confirm = await msg.waitConfirm(
                    f"你是否想要输入{display_prefix}{new_command_display}？")
                if wait_confirm:
                    command_split = [match_close_module[0]]
                    command_first_word = match_close_module[0]
                    msg.trigger_msg = " ".join(command_split)
                    return msg, command_first_word, command_split
    return None, None, None
"""

__all__ = ["parser", "check_temp_ban", "remove_temp_ban"]
