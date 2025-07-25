from core.builtins.message.internal import Image as BImage
from core.component import module
from core.logger import Logger
from core.scheduler import CronTrigger
from core.utils.message import isint
from .database.models import DivingProberBindInfo
from .libraries.maimaidx_apidata import get_alias, get_info, search_by_alias, update_alias, update_cover
from .libraries.maimaidx_best50 import generate as generate_b50
from .libraries.maimaidx_platelist import generate as generate_plate
from .libraries.maimaidx_utils import *

total_list = TotalList()

mai = module(
    "maimai",
    recommend_modules="maimai_regex",
    developers=["mai-bot", "OasisAkari", "DoroWolf"],
    alias="mai",
    support_languages=["zh_cn"],
    desc="{I18N:maimai.help.desc}",
    doc=True,
)


@mai.command(
    "base <constant> [<constant_max>] [-p <page>] {{I18N:maimai.help.base}}",
    options_desc={"-p": "{I18N:maimai.help.option.p}"}
)
async def _(msg: Bot.MessageSession, constant: float, constant_max: float = None):
    result_set = []
    if constant <= 0:
        await msg.finish(I18NContext("maimai.message.level_invalid"))
    elif constant_max:
        if constant > constant_max:
            data = (await total_list.get()).filter(ds=(constant_max, constant))
            s = (
                msg.session_info.locale.t(
                    "maimai.message.base.range",
                    constant=round(constant_max, 1),
                    constant_max=round(constant, 1),
                )
                + "\n"
            )
        else:
            data = (await total_list.get()).filter(ds=(constant, constant_max))
            s = (
                msg.session_info.locale.t(
                    "maimai.message.base.range",
                    constant=round(constant, 1),
                    constant_max=round(constant_max, 1),
                )
                + "\n"
            )
    else:
        data = (await total_list.get()).filter(ds=constant)
        s = msg.session_info.locale.t("maimai.message.base", constant=round(constant, 1)) + "\n"

    for music in sorted(data, key=lambda i: int(i["id"])):
        for i in music.diff:
            if int(music["id"]) < 100000:  # 过滤宴谱
                result_set.append(
                    (
                        music["id"],
                        music["title"],
                        music["ds"][i],
                        diff_list[i],
                        music["level"][i],
                        music["type"],
                    )
                )

    total_pages = (len(result_set) + SONGS_PER_PAGE - 1) // SONGS_PER_PAGE
    get_page = msg.parsed_msg.get("-p", False)
    if get_page and isint(get_page["<page>"]):
        page = max(min(int(get_page["<page>"]), total_pages), 1)
    else:
        page = 1
    start_index = (page - 1) * SONGS_PER_PAGE
    end_index = page * SONGS_PER_PAGE

    for elem in result_set[start_index:end_index]:
        s += f"{elem[0]} - {elem[1]}{" (DX)" if elem[5] == "DX" else ""} {elem[3]} {elem[4]} ({elem[2]})\n"
    if len(result_set) == 0:
        await msg.finish(I18NContext("maimai.message.music_not_found"))
    elif len(result_set) <= SONGS_PER_PAGE:
        await msg.finish(s.strip())
    else:
        s += msg.session_info.locale.t("maimai.message.pages", page=page, total_pages=total_pages)
        imgs = await msgchain2image(Plain(s))
        if imgs:
            await msg.finish(imgs)
        else:
            await msg.finish(s)


@mai.command(
    "level <level> [-p <page>] {{I18N:maimai.help.level}}",
    options_desc={"-p": "{I18N:maimai.help.option.p}"}
)
async def _(msg: Bot.MessageSession, level: str):
    result_set = []
    data = (await total_list.get()).filter(level=level)
    for music in sorted(data, key=lambda i: int(i["id"])):
        for i in music.diff:
            if int(music["id"]) < 100000:  # 过滤宴谱
                result_set.append(
                    (
                        music["id"],
                        music["title"],
                        music["ds"][i],
                        diff_list[i],
                        music["level"][i],
                        music["type"],
                    )
                )
    total_pages = (len(result_set) + SONGS_PER_PAGE - 1) // SONGS_PER_PAGE
    get_page = msg.parsed_msg.get("-p", False)
    page = (
        max(min(int(get_page["<page>"]), total_pages), 1)
        if get_page and isint(get_page["<page>"])
        else 1
    )
    start_index = (page - 1) * SONGS_PER_PAGE
    end_index = page * SONGS_PER_PAGE

    s = msg.session_info.locale.t("maimai.message.level", level=level) + "\n"
    for elem in result_set[start_index:end_index]:
        s += f"{elem[0]} - {elem[1]}{" (DX)" if elem[5] == "DX" else ""} {elem[3]} {elem[4]} ({elem[2]})\n"

    if len(result_set) == 0:
        await msg.finish(I18NContext("maimai.message.music_not_found"))
    elif len(result_set) <= SONGS_PER_PAGE:
        await msg.finish(s.strip())
    else:
        s += msg.session_info.locale.t("maimai.message.pages", page=page, total_pages=total_pages)
        imgs = await msgchain2image(Plain(s))
        if imgs:
            await msg.finish(imgs)
        else:
            await msg.finish(s)


@mai.command(
    "new [-p <page>] {{I18N:maimai.help.new}}",
    options_desc={"-p": "{I18N:maimai.help.option.p}"}
)
async def _(msg: Bot.MessageSession):
    result_set = []
    data = (await total_list.get()).new()

    for music in sorted(data, key=lambda i: int(i["id"])):
        result_set.append((music["id"], music["title"], music["type"]))
    total_pages = (len(result_set) + SONGS_PER_PAGE - 1) // SONGS_PER_PAGE
    get_page = msg.parsed_msg.get("-p", False)
    page = (
        max(min(int(get_page["<page>"]), total_pages), 1)
        if get_page and isint(get_page["<page>"])
        else 1
    )
    start_index = (page - 1) * SONGS_PER_PAGE
    end_index = page * SONGS_PER_PAGE

    s = msg.session_info.locale.t("maimai.message.new") + "\n"
    for elem in result_set[start_index:end_index]:
        s += f"{elem[0]} - {elem[1]}{" (DX)" if elem[2] == "DX" else ""}\n"

    if len(result_set) == 0:
        await msg.finish(I18NContext("maimai.message.music_not_found"))
    elif len(result_set) <= SONGS_PER_PAGE:
        await msg.finish(s.strip())
    else:
        s += msg.session_info.locale.t("maimai.message.pages", page=page, total_pages=total_pages)
        imgs = await msgchain2image(Plain(s))
        if imgs:
            await msg.finish(imgs)
        else:
            await msg.finish(s)


@mai.command(
    "search <keyword> [-p <page>] {{I18N:maimai.help.search}}",
    options_desc={"-p": "{I18N:maimai.help.option.p}"},
)
async def _(msg: Bot.MessageSession, keyword: str):
    name = keyword.strip()
    result_set = []
    data = (await total_list.get()).filter(title_search=name)
    if len(data) == 0:
        await msg.finish(I18NContext("maimai.message.music_not_found"))

    for music in sorted(data, key=lambda i: int(i["id"])):
        result_set.append((music["id"], music["title"], music["type"]))
    total_pages = (len(result_set) + SONGS_PER_PAGE - 1) // SONGS_PER_PAGE
    get_page = msg.parsed_msg.get("-p", False)
    page = (
        max(min(int(get_page["<page>"]), total_pages), 1)
        if get_page and isint(get_page["<page>"])
        else 1
    )
    start_index = (page - 1) * SONGS_PER_PAGE
    end_index = page * SONGS_PER_PAGE

    s = msg.session_info.locale.t("maimai.message.search", keyword=name) + "\n"
    for elem in result_set[start_index:end_index]:
        s += f"{elem[0]} - {elem[1]}{" (DX)" if elem[2] == "DX" else ""}\n"
    if len(data) <= SONGS_PER_PAGE:
        await msg.finish(s.strip())
    else:
        s += msg.session_info.locale.t("maimai.message.pages", page=page, total_pages=total_pages)
        imgs = await msgchain2image(Plain(s))
        if imgs:
            await msg.finish(imgs)
        else:
            await msg.finish(s)


@mai.command("alias <sid> {{I18N:maimai.help.alias}}")
async def _(msg: Bot.MessageSession, sid: str):
    if not isint(sid):
        if sid[:2].lower() == "id":
            sid = sid[2:]
        else:
            await msg.finish(I18NContext("maimai.message.id_invalid"))
    await query_alias(msg, sid)


async def query_alias(msg, sid):
    music = (await total_list.get()).by_id(sid)
    if not music:
        await msg.finish(I18NContext("maimai.message.music_not_found"))

    title = (
        f"{music["id"]} - {music["title"]}{" (DX)" if music["type"] == "DX" else ""}"
    )
    alias = await get_alias(msg, sid)
    if len(alias) == 0:
        await msg.finish(I18NContext("maimai.message.alias.alias_not_found"))
    else:
        res = [I18NContext("maimai.message.alias", title=title)]
        res += [Plain(a) for a in alias]

        if len(alias) >= 20:
            imgs = await msgchain2image(res, msg)
            if imgs:
                await msg.finish(imgs)
            else:
                await msg.finish(res)
        else:
            await msg.finish(res)


@mai.command("grade <grade> {{I18N:maimai.help.grade}}")
async def _(msg: Bot.MessageSession, grade: str):
    await get_grade_info(msg, grade)


@mai.command("bind <username> {{I18N:maimai.help.bind}}", exclude_from=["QQ|Private", "QQ|Group"])
async def _(msg: Bot.MessageSession, username: str):
    await get_record(msg, {"username": username}, use_cache=False)
    await DivingProberBindInfo.set_bind_info(sender_id=msg.session_info.sender_id, username=username)
    await msg.finish(msg.session_info.locale.t("maimai.message.bind.success") + username)


@mai.command("unbind {{I18N:maimai.help.unbind}}", exclude_from=["QQ|Private", "QQ|Group"])
async def _(msg: Bot.MessageSession):
    await DivingProberBindInfo.remove_bind_info(sender_id=msg.session_info.sender_id)
    await msg.finish(I18NContext("maimai.message.unbind.success"))


@mai.command("b50 [<username>] {{I18N:maimai.help.b50}}")
async def _(msg: Bot.MessageSession, username: str = None):
    if not username:
        if msg.session_info.sender_from == "QQ":
            payload = {"qq": msg.session_info.sender_id.split("|")[-1], "b50": True}
        else:
            bind_info = await DivingProberBindInfo.get_by_sender_id(msg, create=False)
            if not bind_info:
                await msg.finish(I18NContext("maimai.message.user_unbound", prefix=msg.session_info.prefixes[0]))
            username = bind_info.username
            payload = {"username": username, "b50": True}
        use_cache = True
    else:
        payload = {"username": username, "b50": True}
        use_cache = False

    img = await generate_b50(msg, payload, use_cache)
    await msg.finish([BImage(img)])


@mai.command("chart <id_or_alias> {{I18N:maimai.help.chart}}")
async def _(msg: Bot.MessageSession, id_or_alias: str):
    if id_or_alias[:2].lower() == "id":
        sid = id_or_alias[2:]
    else:
        sid_list = await search_by_alias(id_or_alias)
        if len(sid_list) == 0:
            await msg.finish(I18NContext("maimai.message.music_not_found"))
        elif len(sid_list) > 1:
            res = msg.session_info.locale.t("maimai.message.disambiguation") + "\n"
            for sid in sorted(sid_list, key=int):
                s = (await total_list.get()).by_id(sid)
                if s:
                    res += f"{s["id"]} - {s["title"]}{" (DX)" if s["type"] == "DX" else ""}\n"
            res += msg.session_info.locale.t("maimai.message.chart.prompt", prefix=msg.session_info.prefixes[0])
            await msg.finish(res)
        else:
            sid = str(sid_list[0])
    music = (await total_list.get()).by_id(sid)
    if not music:
        await msg.finish(I18NContext("maimai.message.music_not_found"))

    res = []
    if int(sid) > 100000:
        with open(mai_utage_info_path, "rb") as file:
            utage_data = json.loads(file.read())

        res.append(f"「{utage_data[sid]["comment"]}」")
        if utage_data[sid]["referrals_num"]["mode"] == "normal":
            chart = utage_data[sid]["charts"][0]
            res.append(
                msg.session_info.locale.t(
                    "maimai.message.chart.utage",
                    level=utage_data[sid]["level"][0],
                    player=utage_data[sid]["referrals_num"]["player"][0],
                    tap=chart["notes"][0],
                    hold=chart["notes"][1],
                    slide=chart["notes"][2],
                    touch=chart["notes"][3],
                    brk=chart["notes"][4],
                )
            )
        else:
            chartL = utage_data[sid]["charts"][0]
            chartR = utage_data[sid]["charts"][1]
            players = utage_data[sid]["referrals_num"]["player"]
            res.append(
                msg.session_info.locale.t(
                    "maimai.message.chart.utage.buddy",
                    level=utage_data[sid]["level"][0],
                    playerL=players[0],
                    playerR=players[1],
                    tapL=chartL["notes"][0],
                    tapR=chartR["notes"][0],
                    holdL=chartL["notes"][1],
                    holdR=chartR["notes"][1],
                    slideL=chartL["notes"][2],
                    slideR=chartR["notes"][2],
                    touchL=chartL["notes"][3],
                    touchR=chartR["notes"][3],
                    brkL=chartL["notes"][4],
                    brkR=chartR["notes"][4],
                )
            )
    else:
        for diff, ds in enumerate(music["ds"]):
            chart = music["charts"][diff]
            if len(chart["notes"]) == 4:
                res.append(
                    msg.session_info.locale.t(
                        "maimai.message.chart.sd",
                        diff=diff_list[diff],
                        level=music["level"][diff],
                        ds=ds,
                        tap=chart["notes"][0],
                        hold=chart["notes"][1],
                        slide=chart["notes"][2],
                        brk=chart["notes"][3],
                    )
                )
                if diff >= 2:
                    res.append(
                        msg.session_info.locale.t("maimai.message.chart.charter") + chart["charter"]
                    )
            else:
                res.append(
                    msg.session_info.locale.t(
                        "maimai.message.chart.dx",
                        diff=diff_list[diff],
                        level=music["level"][diff],
                        ds=ds,
                        tap=chart["notes"][0],
                        hold=chart["notes"][1],
                        slide=chart["notes"][2],
                        touch=chart["notes"][3],
                        brk=chart["notes"][4],
                    )
                )
                if diff >= 2:
                    res.append(
                        msg.session_info.locale.t("maimai.message.chart.charter") + chart["charter"]
                    )

    await msg.finish(await get_info(music, Plain("\n".join(res))))


@mai.command("id <id> {{I18N:maimai.help.id}}")
@mai.command("song <id_or_alias> {{I18N:maimai.help.song}}")
async def _(msg: Bot.MessageSession, id_or_alias: str):
    if "<id>" in msg.parsed_msg:
        sid = msg.parsed_msg["<id>"]
    elif id_or_alias[:2].lower() == "id":
        sid = id_or_alias[2:]
    else:
        sid_list = await search_by_alias(id_or_alias)
        if len(sid_list) == 0:
            await msg.finish(I18NContext("maimai.message.music_not_found"))
        elif len(sid_list) > 1:
            res = msg.session_info.locale.t("maimai.message.disambiguation") + "\n"
            for sid in sorted(sid_list, key=int):
                s = (await total_list.get()).by_id(sid)
                if s:
                    res += f"{s["id"]} - {s["title"]}{" (DX)" if s["type"] == "DX" else ""}\n"
            res += msg.session_info.locale.t("maimai.message.song.prompt", prefix=msg.session_info.prefixes[0])
            await msg.finish(res)
        else:
            sid = str(sid_list[0])
    music = (await total_list.get()).by_id(sid)
    if not music:
        await msg.finish(I18NContext("maimai.message.music_not_found"))

    if int(sid) > 100000:
        res = []
        with open(mai_utage_info_path, "rb") as file:
            utage_data = json.loads(file.read())
        if utage_data:
            try:
                res.append(f"「{utage_data[sid]["comment"]}」")
            except KeyError:
                res.append("「Let's party!」")

        res.append(msg.session_info.locale.t(
            "maimai.message.song",
            artist=music["basic_info"]["artist"],
            genre="宴會場",
            bpm=music["basic_info"]["bpm"],
            version=music["basic_info"]["from"],
            level=music["level"][0]
        ))
        res = "\n".join(res)
    else:
        res = msg.session_info.locale.t(
            "maimai.message.song",
            artist=music["basic_info"]["artist"],
            genre=genre_i18n_mapping.get(
                music["basic_info"]["genre"], music["basic_info"]["genre"]
            ),
            bpm=music["basic_info"]["bpm"],
            version=music["basic_info"]["from"],
            level="/".join((str(ds) for ds in music["ds"])),
        )
    await msg.finish(await get_info(music, Plain(res)))


@mai.command(
    "score <id_or_alias> [-u <username>] {{I18N:maimai.help.score}}",
    options_desc={"-u": "{I18N:maimai.help.option.u}"},
)
async def _(msg: Bot.MessageSession, id_or_alias: str):
    get_user = msg.parsed_msg.get("-u", False)
    username = get_user["<username>"] if get_user else None
    await query_song_score(msg, id_or_alias, username)


async def query_song_score(msg, query, username):
    if query[:2].lower() == "id":
        sid = query[2:]
    else:
        sid_list = await search_by_alias(query)

        if len(sid_list) == 0:
            await msg.finish(I18NContext("maimai.message.music_not_found"))
        elif len(sid_list) > 1:
            res = msg.session_info.locale.t("maimai.message.disambiguation") + "\n"
            for sid in sorted(sid_list, key=int):
                s = (await total_list.get()).by_id(sid)
                if s:
                    res += f"{s["id"]} - {s["title"]}{" (DX)" if s["type"] == "DX" else ""}\n"
            res += msg.session_info.locale.t("maimai.message.score.prompt", prefix=msg.session_info.prefixes[0])
            await msg.finish(res)
        else:
            sid = str(sid_list[0])

    music = (await total_list.get()).by_id(sid)
    if not music:
        await msg.finish(I18NContext("maimai.message.music_not_found"))

    if not username:
        if msg.session_info.sender_from == "QQ":
            payload = {"qq": msg.session_info.sender_id.split("|")[-1]}
        else:
            bind_info = await DivingProberBindInfo.get_by_sender_id(msg, create=False)
            if not bind_info:
                await msg.finish(I18NContext("maimai.message.user_unbound", prefix=msg.session_info.prefixes[0]))
            username = bind_info.username
            payload = {"username": username}
        use_cache = True
    else:
        payload = {"username": username}
        use_cache = False

    output = await get_player_score(msg, payload, sid, use_cache)
    await msg.finish(await get_info(music, output))


@mai.command("plate <plate> [<username>] [-l] {{I18N:maimai.help.plate}}",
             options_desc={"-l": "{I18N:maimai.help.option.l}"})
async def _(msg: Bot.MessageSession, plate: str, username: str = None):
    get_list = msg.parsed_msg.get("-l", False)
    await query_plate(msg, plate, username, get_list)


async def query_plate(msg, plate, username, get_list=False):
    if not username:
        if msg.session_info.sender_from == "QQ":
            payload = {"qq": msg.session_info.sender_id.split("|")[-1]}
        else:
            bind_info = await DivingProberBindInfo.get_by_sender_id(msg, create=False)
            if not bind_info:
                await msg.finish(I18NContext("maimai.message.user_unbound", prefix=msg.session_info.prefixes[0]))
            username = bind_info.username
            payload = {"username": username}
        use_cache = True
    else:
        payload = {"username": username}
        use_cache = False

    if plate in ["真将", "真將"] or (plate[1] == "者" and plate[0] not in ["覇", "霸"]):
        await msg.finish(I18NContext("maimai.message.plate.plate_not_found"))

    if get_list:
        img = await generate_plate(msg, payload, plate, use_cache)
        await msg.finish([BImage(img)])
    else:
        output, get_img = await get_plate_process(msg, payload, plate, use_cache)

        if get_img:
            imgs = await msgchain2image(output, msg)
            if imgs:
                await msg.finish(imgs)
            else:
                await msg.finish(output)
        else:
            await msg.finish(output)


@mai.command("process <level> <goal> [<username>] {{I18N:maimai.help.process}}")
async def _(msg: Bot.MessageSession, level: str, goal: str, username: str = None):
    await query_process(msg, level, goal, username)


async def query_process(msg, level, goal, username):
    if not username:
        if msg.session_info.sender_from == "QQ":
            payload = {"qq": msg.session_info.sender_id.split("|")[-1]}
        else:
            bind_info = await DivingProberBindInfo.get_by_sender_id(msg, create=False)
            if not bind_info:
                await msg.finish(I18NContext("maimai.message.user_unbound", prefix=msg.session_info.prefixes[0]))
            username = bind_info.username
            payload = {"username": username}
        use_cache = True
    else:
        payload = {"username": username}
        use_cache = False

    if level not in level_list:
        await msg.finish(I18NContext("maimai.message.level_invalid"))
    if goal.upper() not in goal_list:
        await msg.finish(I18NContext("maimai.message.goal_invalid"))

    output, get_img = await get_level_process(msg, payload, level, goal, use_cache)

    if get_img:
        imgs = await msgchain2image(output, msg)
        if imgs:
            await msg.finish(imgs)
        else:
            await msg.finish(output)
    else:
        await msg.finish(output)


@mai.command("rank [<username>] {{I18N:maimai.help.rank}}")
async def _(msg: Bot.MessageSession, username: str = None):
    if not username:
        if msg.session_info.sender_from == "QQ":
            payload = {"qq": msg.session_info.sender_id.split("|")[-1]}
        else:
            bind_info = await DivingProberBindInfo.get_by_sender_id(msg, create=False)
            if not bind_info:
                await msg.finish(I18NContext("maimai.message.user_unbound", prefix=msg.session_info.prefixes[0]))
            username = bind_info.username
            payload = {"username": username}
        use_cache = True
    else:
        payload = {"username": username}
        use_cache = False

    await get_rank(msg, payload, use_cache)


@mai.command(
    "scorelist <level> [-p <page>] [-u <username>] {{I18N:maimai.help.scorelist}}",
    options_desc={"-p": "{I18N:maimai.help.option.p}",
                  "-u": "{I18N:maimai.help.option.u}"}
)
async def _(msg: Bot.MessageSession, level: str):
    get_user = msg.parsed_msg.get("-u", False)
    username = get_user["<username>"] if get_user else None
    get_page = msg.parsed_msg.get("-p", False)
    page = get_page["<page>"] if get_page and isint(get_page["<page>"]) else 1
    if not username:
        if msg.session_info.sender_from == "QQ":
            payload = {"qq": msg.session_info.sender_id.split("|")[-1]}
        else:
            bind_info = await DivingProberBindInfo.get_by_sender_id(msg, create=False)
            if not bind_info:
                await msg.finish(I18NContext("maimai.message.user_unbound", prefix=msg.session_info.prefixes[0]))
            username = bind_info.username
            payload = {"username": username}
        use_cache = True
    else:
        payload = {"username": username}
        use_cache = False

    output, get_img = await get_score_list(msg, payload, level, page, use_cache)

    if get_img:
        imgs = await msgchain2image(output, msg)
        if imgs:
            await msg.finish(imgs)
        else:
            await msg.finish(output)
    else:
        await msg.finish(output)


@mai.command("random <diff+level> [<dx_type>] {{I18N:maimai.help.random.filter}}")
async def _(msg: Bot.MessageSession, dx_type: str = None):
    condit = msg.parsed_msg["<diff+level>"]
    level = ""
    diff = ""
    try:
        if dx_type in ["dx", "DX"]:
            dx_type_lst = ["DX"]
        elif dx_type in ["sd", "SD", "标准", "標準"]:
            dx_type_lst = ["SD"]
        else:
            dx_type_lst = ["SD", "DX"]

        for char in condit:
            if isint(char) or char == "+":
                level += char
            else:
                diff += char

        if level == "":
            if diff == "*":
                music_data = (await total_list.get()).filter(dxtype=dx_type_lst)
            else:
                raise ValueError
        else:
            if diff == "":
                music_data = (await total_list.get()).filter(
                    level=level, dxtype=dx_type_lst
                )
            else:
                music_data = (await total_list.get()).filter(
                    level=level, diff=[get_diff(diff)], dxtype=dx_type_lst
                )

        if len(music_data) == 0:
            await msg.finish(I18NContext("maimai.message.music_not_found"))
        else:
            music = music_data.random()
            await msg.finish(
                await get_info(music, Plain(f"{"/".join(str(ds) for ds in music.ds)}"))
            )
    except (ValueError, TypeError):
        await msg.finish(I18NContext("maimai.message.random.failed"))


@mai.command("random {{I18N:maimai.help.random}}")
async def _(msg: Bot.MessageSession):
    music = (await total_list.get()).random()
    await msg.finish(
        await get_info(music, Plain(f"{"/".join(str(ds) for ds in music.ds)}"))
    )


@mai.command("scoreline <sid> <diff> <score> {{I18N:maimai.help.scoreline}}")
async def _(msg: Bot.MessageSession, diff: str, sid: str, score: float):
    try:
        if not isint(sid):
            if sid[:2].lower() == "id":
                sid = sid[2:]
            else:
                await msg.finish(I18NContext("maimai.message.id_invalid"))
        diff_index = get_diff(diff)
        music = (await total_list.get()).by_id(sid)
        chart = music["charts"][diff_index]
        tap = int(chart["notes"][0])
        slide = int(chart["notes"][2])
        hold = int(chart["notes"][1])
        touch = int(chart["notes"][3]) if len(chart["notes"]) == 5 else 0
        brk = int(chart["notes"][-1])
        total_score = (
            500 * tap + slide * 1500 + hold * 1000 + touch * 500 + brk * 2500
        )  # 基础分
        bonus_score = total_score * 0.01 / brk  # 奖励分
        break_2550_reduce = bonus_score * 0.25  # 一个 BREAK 2550 减少 25% 奖励分
        break_2000_reduce = (
            bonus_score * 0.6 + 500
        )  # 一个 BREAK 2000 减少 500 基础分和 60% 奖励分
        reduce = 101 - score  # 理论值与给定完成率的差，以百分比计
        if reduce <= 0 or reduce >= 101:
            raise ValueError
        tap_great = (
            f"{(total_score * reduce / 10000):.2f}"  # 一个 TAP GREAT 减少 100 分
        )
        tap_great_prop = f"{(10000 / total_score):.4f}"
        b2t_2550_great = (
            f"{(break_2550_reduce / 100):.3f}"  # 一个 TAP GREAT 减少 100 分
        )
        b2t_2550_great_prop = f"{(break_2550_reduce / total_score * 100):.4f}"
        b2t_2000_great = (
            f"{(break_2000_reduce / 100):.3f}"  # 一个 TAP GREAT 减少 100 分
        )
        b2t_2000_great_prop = f"{(break_2000_reduce / total_score * 100):.4f}"
        await msg.finish(
            f"""{music["title"]}{" (DX)" if music["type"] == "DX" else ""} {diff_list[diff_index]}
{msg.session_info.locale.t("maimai.message.scoreline",
                           scoreline=score,
                           tap_great=tap_great,
                           tap_great_prop=tap_great_prop,
                           brk=brk,
                           b2t_2550_great=b2t_2550_great,
                           b2t_2550_great_prop=b2t_2550_great_prop,
                           b2t_2000_great=b2t_2000_great,
                           b2t_2000_great_prop=b2t_2000_great_prop)}"""
        )
    except ValueError:
        await msg.finish(
            msg.session_info.locale.t("maimai.message.scoreline.failed", prefix=msg.session_info.prefixes[0])
        )


@mai.command("calc <base> <score> {{I18N:maimai.help.calc}}")
async def _(msg: Bot.MessageSession, base: float, score: float):
    await msg.finish(Plain(compute_rating(base, score)))


@mai.command("update [--no-cover]", required_superuser=True)
async def _(msg: Bot.MessageSession):
    if msg.parsed_msg.get("--no-cover", False):
        actions = await update_alias() and await total_list.update()
    else:
        actions = (
            await update_alias() and await update_cover() and await total_list.update()
        )
    if actions:
        await msg.finish(I18NContext("message.success"))
    else:
        await msg.finish(I18NContext("message.failed"))


@mai.schedule(CronTrigger.from_crontab("0 0 * * *"))
async def _():
    Logger.info("Updating Maimai alias...")
    await update_alias()
