from core.builtins.bot import Bot
from core.builtins.message.internal import I18NContext
from core.component import module
from core.config import Config
from modules.osu.database.models import OsuBindInfo
from .profile import osu_profile
from .utils import get_profile_name

api_key = Config("osu_api_key", cfg_type=str, secret=True, table_name="module_osu")

osu = module("osu", developers=["DoroWolf"], desc="{I18N:osu.help.desc}", doc=True)


@osu.command(
    "profile [<username>] [-t <mode>] {{I18N:osu.help.profile}}",
    options_desc={"-t": "{I18N:osu.help.option.t}"},
)
async def _(msg: Bot.MessageSession, username: str = None):
    if username:
        query_id = username.lower()
    else:
        bind_info = await OsuBindInfo.get_by_sender_id(msg, create=False)
        if not bind_info:
            await msg.finish(I18NContext("osu.message.user_unbound", prefix=msg.session_info.prefixes[0]))
        query_id = bind_info.username
    get_mode = msg.parsed_msg.get("-t", False)
    mode = get_mode["<mode>"] if get_mode else "0"
    await osu_profile(msg, query_id, mode, api_key)


@osu.command("bind <username> {{I18N:osu.help.bind}}")
async def _(msg: Bot.MessageSession, username: str):
    code: str = username.lower()
    getcode = await get_profile_name(code, api_key)
    if getcode:
        await OsuBindInfo.set_bind_info(sender_id=msg.session_info.sender_id, username=getcode[0])
        if getcode[1]:
            m = f"{getcode[1]}{str(I18NContext("message.brackets", msg=getcode[0]))}"
        else:
            m = getcode[0]
        await msg.finish(str(I18NContext("osu.message.bind.success")) + m)
    else:
        await msg.finish(I18NContext("osu.message.bind.failed"))


@osu.command("unbind {{I18N:osu.help.unbind}}")
async def _(msg: Bot.MessageSession):
    await OsuBindInfo.remove_bind_info(msg.session_info.sender_id)
    await msg.finish(I18NContext("osu.message.unbind.success"))
