import orjson as json

from core.builtins.bot import Bot
from core.builtins.message.internal import I18NContext, Plain
from core.component import module
from core.dirty_check import check
from core.logger import Logger
from core.utils.http import post_url

n = module("nbnhhsh",
           desc="{I18N:nbnhhsh.help.desc}",
           doc=True,
           developers=["Dianliang233"],
           support_languages=["zh_cn"]
           )


@n.command("<term> {{I18N:nbnhhsh.help}}")
async def _(msg: Bot.MessageSession, term: str):
    res = await nbnhhsh(msg, term)
    await msg.finish([Plain(term.lower()), res])


async def nbnhhsh(msg: Bot.MessageSession, term: str):
    req = json.dumps({"text": term})
    data = await post_url("https://lab.magiconch.com/api/nbnhhsh/guess",
                          data=req,
                          headers={"Content-Type": "application/json",
                                   "Accept": "*/*",
                                   "Content-Length": str(len(req))},
                          fmt="json")
    Logger.debug(data)
    try:
        result = data[0]
    except IndexError:
        await msg.finish(I18NContext("nbnhhsh.message.not_found"))
    if "trans" in result:
        trans = result["trans"]
        if trans:
            chk = await check(trans, session=msg)
            return Plain("、".join(i["content"] for i in chk))
    if "inputting" in result:
        inputting = result["inputting"]
        if inputting:
            chk = await check(inputting, session=msg)
            return I18NContext("nbnhhsh.message.guess", term="、".join(i["content"] for i in chk))
        await msg.finish(I18NContext("nbnhhsh.message.not_found"))
