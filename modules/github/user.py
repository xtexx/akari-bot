from core.builtins.bot import Bot
from core.builtins.message.internal import I18NContext, Plain, Url
from core.dirty_check import rickroll
from core.utils.http import get_url
from modules.github.utils import time_diff, dirty_check, dark_check


async def user(msg: Bot.MessageSession, name: str, pat: str):
    try:
        result = await get_url("https://api.github.com/users/" + name, 200, fmt="json",
                               headers=[("Authorization", f"Bearer {pat}")] if pat else [])
        optional = []
        if "hireable" in result and result["hireable"]:
            optional.append("Hireable")
        if "is_staff" in result and result["is_staff"]:
            optional.append("GitHub Staff")
        if "company" in result and result["company"]:
            optional.append("Work · " + result["company"])
        if "twitter_username" in result and result["twitter_username"]:
            optional.append("Twitter · " + result["twitter_username"])
        if "blog" in result and result["blog"]:
            optional.append("Site · " + result["blog"])
        if "location" in result and result["location"]:
            optional.append("Location · " + result["location"])

        bio = result["bio"]
        if not bio:
            bio = ""
        else:
            bio = "\n" + result["bio"]

        optional_text = "\n" + " | ".join(optional)
        message = f"""{result["login"]} aka {result["name"]} ({result["id"]}){
            bio}
Type · {result["type"]} | Follower · {result["followers"]} | Following · {result["following"]}
                                                              | Repo · {result["public_repos"]} | Gist · {result["public_gists"]}{optional_text}
Account Created {time_diff(result["created_at"])} ago | Latest activity {time_diff(result["updated_at"])} ago
{str(Url(result["html_url"], md_format=msg.session_info.use_url_md_format))}"""

        is_dirty = await dirty_check(message, result["login"]) or dark_check(message)
        if is_dirty:
            await msg.finish(rickroll())

        await msg.finish(Plain(message))
    except ValueError as e:
        if str(e).startswith("404"):
            await msg.finish(I18NContext("github.message.repo.not_found"))
        else:
            raise e
