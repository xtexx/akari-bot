# ported from kurisu(https://github.com/nh-server/Kurisu/tree/main/cogs/results)
import discord

from core.builtins.bot import Bot
from core.builtins.message.internal import I18NContext
from core.component import module
from core.utils.element import convert_discord_embed
from . import switch, wiiu_support, wiiu_results, ctr_support, ctr_results


class Results:
    """
    Parses game console result codes.
    """

    @staticmethod
    def fetch(error):
        if ctr_support.is_valid(error):
            return ctr_support.get(error)
        if ctr_results.is_valid(error):
            return ctr_results.get(error)
        if wiiu_support.is_valid(error):
            return wiiu_support.get(error)
        if wiiu_results.is_valid(error):
            return wiiu_results.get(error)
        if switch.is_valid(error):
            return switch.get(error)

        # Console name, module name, result, color
        return None

    def err2hex(self, error, suppress_error=False):
        # If it's already hex, just return it.
        if self.is_hex(error):
            return error

        # Only Switch is supported. The other two can only give nonsense results.
        if switch.is_valid(error):
            return switch.err2hex(error, suppress_error)

        if not suppress_error:
            return "Invalid or unsupported error code format. \
Only Nintendo Switch XXXX-YYYY formatted error codes are supported."

    def hex2err(self, error, suppress_error=False):
        # Don't bother processing anything if it's not hex.
        if self.is_hex(error):
            if switch.is_valid(error):
                return switch.hex2err(error)
        if not suppress_error:
            return "This isn\'t a hexadecimal value!"

    @staticmethod
    def fixup_input(user_input):
        # Truncate input to 16 chars so as not to create a huge embed or do
        # eventual regex on a huge string. If we add support for consoles that
        # that have longer error codes, adjust accordingly.
        user_input = user_input[:16]

        # Fix up hex input if 0x was omitted. It's fine if it doesn't convert.
        try:
            user_input = hex(int(user_input, 16))
        except ValueError:
            pass

        return user_input

    @staticmethod
    def is_hex(user_input):
        try:
            user_input = hex(int(user_input, 16))
        except ValueError:
            return False
        return True

    @staticmethod
    def check_meme(err: str) -> str:
        memes = {
            "0xdeadbeef": "nintendo_err.message.meme.0xdeadbeef",
            "0xdeadbabe": "nintendo_err.message.meme.0xdeadbabe",
            "0x8badf00d": "nintendo_err.message.meme.0xbadf00d",
        }
        return memes.get(err.casefold())


e = module("nintendo_err", alias=["err"], developers=["OasisAkari", "kurisu"], doc=True)


@e.command("<err_code> {{I18N:nintendo_err.help}}")
async def _(msg: Bot.MessageSession, err_code: str):
    results = Results()
    err = results.fixup_input(err_code)
    if meme := results.check_meme(err):
        await msg.finish(I18NContext(meme))
    try:
        ret = results.fetch(err)
    except ValueError:
        ret = None

    if ret:
        embed = discord.Embed(title=ret.get_title())
        if ret.extra_description:
            embed.description = ret.extra_description
        for field in ret:
            embed.add_field(name=field.field_name, value=field.message, inline=False)
        await msg.finish(convert_discord_embed(embed))
    else:
        await msg.finish(I18NContext("nintendo_err.message.invalid"))
