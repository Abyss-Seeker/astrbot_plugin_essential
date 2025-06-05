import random
import asyncio
import os
import json
import datetime
import aiohttp
import urllib.parse
import logging
from PIL import Image as PILImage
from PIL import ImageDraw as PILImageDraw
from PIL import ImageFont as PILImageFont
from astrbot.api.all import AstrMessageEvent, CommandResult, Context, Image, Plain
import astrbot.api.event.filter as filter
from astrbot.api.star import register, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

logger = logging.getLogger("astrbot")


@register("astrbot_plugin_essential", "Soulter", "", "", "")
class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.PLUGIN_NAME = "astrbot_plugin_essential"
        PLUGIN_NAME = self.PLUGIN_NAME
        path = os.path.abspath(os.path.dirname(__file__))
        self.mc_html_tmpl = open(
            path + "/templates/mcs.html", "r", encoding="utf-8"
        ).read()
        self.what_to_eat_data: list = json.loads(
            open(path + "/resources/food.json", "r", encoding="utf-8").read()
        )["data"]

        if not os.path.exists(f"data/{PLUGIN_NAME}_data.json"):
            with open(f"data/{PLUGIN_NAME}_data.json", "w", encoding="utf-8") as f:
                f.write(json.dumps({}, ensure_ascii=False, indent=2))
        with open(f"data/{PLUGIN_NAME}_data.json", "r", encoding="utf-8") as f:
            self.data = json.loads(f.read())
        self.good_morning_data = self.data.get("good_morning", {})

        # moe
        self.moe_urls = [
            "https://t.mwm.moe/pc/",
            "https://t.mwm.moe/mp",
            "https://www.loliapi.com/acg/",
            "https://www.loliapi.com/acg/pc/",
        ]

        self.search_anmime_demand_users = {}
        # SauceNAO API配置
        self.saucenao_api_key = config.get("SAUCENAO_API_KEY")
        self.saucenao_api_url = "https://saucenao.com/search.php"

    def time_convert(self, t):
        m, s = divmod(t, 60)
        return f"{int(m)}分{int(s)}秒"

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_search_anime(self, message: AstrMessageEvent):
        """检查是否有搜番请求"""
        sender = message.get_sender_id()
        if sender in self.search_anmime_demand_users:
            message_obj = message.message_obj
            image_obj = None

            # 遍历消息链寻找图片（兼容所有平台）
            for comp in message_obj.message:
                if isinstance(comp, Image):
                    image_obj = comp
                    break

            # 微信平台特殊处理
            if not image_obj and message.get_platform_name() in ["gewechat", "wechatpadpro"]:
                raw_msg = message.message_obj.raw_message
                # 尝试从微信原始消息提取图片
                if 'image' in raw_msg:
                    image_obj = Image.fromURL(raw_msg['image'])

            if not image_obj:
                if sender in self.search_anmime_demand_users:
                    del self.search_anmime_demand_users[sender]
                return CommandResult().error("未找到有效的图片数据")

            try:
                # 微信图片需要特殊处理
                image_url = image_obj.url
                if message.get_platform_name() in ["gewechat", "wechatpadpro"]:
                    # 添加微信专用Headers
                    headers = {"Referer": "https://weixin.qq.com/"}
                    # 下载图片到本地（避免URL访问限制）
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, headers=headers) as resp:
                            if resp.status == 200:
                                image_data = await resp.read()
                                with open("temp_wechat_img.jpg", "wb") as f:
                                    f.write(image_data)
                                image_url = "file://" + os.path.abspath("temp_wechat_img.jpg")
                            else:
                                logger.error(f"微信图片下载失败: {resp.status}")
                                return CommandResult().error("图片下载失败，请重试")

                # 使用SauceNAO API - 改用POST请求
                form_data = aiohttp.FormData()
                form_data.add_field('url',
                                    image_url)  # 或者使用文件上传：form_data.add_field('file', open("temp_wechat_img.jpg", 'rb'), filename='image.jpg', content_type='image/jpeg')
                form_data.add_field('api_key', self.saucenao_api_key)
                form_data.add_field('db', '999')
                form_data.add_field('output_type', '2')

                logger.info(f"准备请求SauceNAO API，URL: {self.saucenao_api_url}")

                async with aiohttp.ClientSession() as session:
                    async with session.post(self.saucenao_api_url, data=form_data) as resp:
                        logger.info(f"API响应状态: {resp.status}")
                        if resp.status != 200:
                            error_msg = f"SauceNAO API请求失败: {resp.status}"
                            logger.error(error_msg)
                            # 尝试获取响应内容以获取更多错误信息
                            try:
                                error_content = await resp.text()
                                logger.error(f"API错误响应内容: {error_content[:500]}")
                            except:
                                logger.exception("获取错误响应内容失败")
                            return CommandResult().error(error_msg)

                        # 记录响应内容（调试用）
                        try:
                            data = await resp.json()
                            logger.info("成功解析API返回的JSON数据")
                        except Exception as e:
                            logger.error(f"解析JSON失败: {str(e)}")
                            # 记录原始响应内容以帮助调试
                            try:
                                data_text = await resp.text()
                                logger.debug(f"API原始响应: {data_text[:500]}")
                            except:
                                logger.exception("获取原始响应失败")
                            return CommandResult().error("API返回数据格式错误")

                # 处理SauceNAO返回结果
                if data.get("results") and len(data["results"]) > 0:
                    logger.info(f"收到返回结果，找到 {len(data['results'])} 条记录")
                    best_result = data["results"][0]
                    header = best_result["header"]
                    data_part = best_result["data"]

                    # 提取信息
                    similarity = float(header["similarity"])
                    source = data_part.get("source") or data_part.get("title") or "未知来源"
                    author = data_part.get("member_name") or data_part.get("author") or "未知作者"
                    ext_urls = data_part.get("ext_urls", [])

                    logger.info(f"相似度: {similarity}%, 番名: {source}, 作者: {author}")

                    warn = ""
                    if similarity < 80.0:
                        warn = "相似度过低，可能不是同一番剧。建议：相同尺寸大小的截图; 去除四周的黑边\n\n"
                        logger.warning("相似度过低警告")

                    if sender in self.search_anmime_demand_users:
                        logger.info("清除用户搜番状态")
                        del self.search_anmime_demand_users[sender]

                    result_text = (
                        f"{warn}番名: {source}\n"
                        f"相似度: {similarity}%\n"
                        f"作者: {author}\n"
                    )

                    if ext_urls:
                        result_text += f"来源: {ext_urls[0]}\n"
                        logger.info(f"来源链接: {ext_urls[0]}")

                    logger.info("返回搜番结果")
                    return CommandResult(
                        chain=[Plain(result_text)],
                        use_t2i_=False,
                    )
                else:
                    logger.info("API返回结果为空")
                    if sender in self.search_anmime_demand_users:
                        del self.search_anmime_demand_users[sender]
                    return CommandResult(True, False, [Plain("没有找到番剧")], "sf")

            except aiohttp.ClientError as e:
                logger.error(f"网络请求异常: {type(e).__name__} - {str(e)}")
                return CommandResult().error("网络连接异常，请稍后重试")
            except Exception as e:
                logger.exception("搜番处理异常")
                return CommandResult().error(f"处理失败: {str(e)}")

    @filter.command("喜报")
    async def congrats(self, message: AstrMessageEvent):
        """喜报生成器"""
        msg = message.message_str.replace("喜报", "").strip()
        for i in range(20, len(msg), 20):
            msg = msg[:i] + "\n" + msg[i:]

        path = os.path.abspath(os.path.dirname(__file__))
        bg = path + "/congrats.jpg"
        img = PILImage.open(bg)
        draw = PILImageDraw.Draw(img)
        font = PILImageFont.truetype(path + "/simhei.ttf", 65)

        # Calculate the width and height of the text
        text_width, text_height = draw.textbbox((0, 0), msg, font=font)[2:4]

        # Calculate the starting position of the text to center it.
        x = (img.size[0] - text_width) / 2
        y = (img.size[1] - text_height) / 2

        draw.text(
            (x, y),
            msg,
            font=font,
            fill=(255, 0, 0),
            stroke_width=3,
            stroke_fill=(255, 255, 0),
        )

        img.save("congrats_result.jpg")
        return CommandResult().file_image("congrats_result.jpg")

    @filter.command("悲报")
    async def uncongrats(self, message: AstrMessageEvent):
        """悲报生成器"""
        msg = message.message_str.replace("悲报", "").strip()
        for i in range(20, len(msg), 20):
            msg = msg[:i] + "\n" + msg[i:]

        path = os.path.abspath(os.path.dirname(__file__))
        bg = path + "/uncongrats.jpg"
        img = PILImage.open(bg)
        draw = PILImageDraw.Draw(img)
        font = PILImageFont.truetype(path + "/simhei.ttf", 65)

        # Calculate the width and height of the text
        text_width, text_height = draw.textbbox((0, 0), msg, font=font)[2:4]

        # Calculate the starting position of the text to center it.
        x = (img.size[0] - text_width) / 2
        y = (img.size[1] - text_height) / 2

        draw.text(
            (x, y),
            msg,
            font=font,
            fill=(0, 0, 0),
            stroke_width=3,
            stroke_fill=(255, 255, 255),
        )

        img.save("uncongrats_result.jpg")
        return CommandResult().file_image("uncongrats_result.jpg")

    @filter.command("moe")
    async def get_moe(self, message: AstrMessageEvent):
        """随机动漫图片"""
        shuffle = random.sample(self.moe_urls, len(self.moe_urls))
        for url in shuffle:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return CommandResult().error(f"获取图片失败: {resp.status}")
                        data = await resp.read()
                        break
            except Exception as e:
                logger.error(f"从 {url} 获取图片失败: {e}。正在尝试下一个API。")
                continue
        # 保存图片到本地
        try:
            with open("moe.jpg", "wb") as f:
                f.write(data)
            return CommandResult().file_image("moe.jpg")

        except Exception as e:
            return CommandResult().error(f"保存图片失败: {e}")

    @filter.command("搜番")
    async def get_search_anime(self, message: AstrMessageEvent):
        """以图搜番"""
        sender = message.get_sender_id()
        if sender in self.search_anmime_demand_users:
            yield message.plain_result("正在等你发图喵，请不要重复发送")
        self.search_anmime_demand_users[sender] = False
        yield message.plain_result("请在 30 喵内发送一张图片让我识别喵")
        await asyncio.sleep(30)
        if sender in self.search_anmime_demand_users:
            if self.search_anmime_demand_users[sender]:
                del self.search_anmime_demand_users[sender]
                return
            del self.search_anmime_demand_users[sender]
            yield message.plain_result("🧐你没有发送图片，搜番请求已取消了喵")

    @filter.command("mcs")
    async def mcs(self, message: AstrMessageEvent):
        """查mc服务器"""
        message_str = message.message_str
        if message_str == "mcs":
            return CommandResult().error("查 Minecraft 服务器。格式: /mcs [服务器地址]")
        ip = message_str.replace("mcs", "").strip()
        url = f"https://api.mcsrvstat.us/2/{ip}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return CommandResult().error("请求失败")
                data = await resp.json()
                logger.info(f"获取到 {ip} 的服务器信息。")

        # result = await context.image_renderer.render_custom_template(self.mc_html_tmpl, data, return_url=True)
        motd = "查询失败"
        if (
            "motd" in data
            and isinstance(data["motd"], dict)
            and isinstance(data["motd"].get("clean"), list)
        ):
            motd_lines = [
                i.strip()
                for i in data["motd"]["clean"]
                if isinstance(i, str) and i.strip()
            ]
            motd = "\n".join(motd_lines) if motd_lines else "查询失败"

        players = "查询失败"
        version = "查询失败"
        if "error" in data:
            return CommandResult().error(f"查询失败: {data['error']}")

        name_list = []

        if "players" in data:
            players = f"{data['players']['online']}/{data['players']['max']}"

            if "list" in data["players"]:
                name_list = data["players"]["list"]

        if "version" in data:
            version = str(data["version"])

        status = "🟢" if data["online"] else "🔴"

        name_list_str = ""
        if name_list:
            name_list_str = "\n".join(name_list)
        if not name_list_str:
            name_list_str = "无玩家在线"

        result_text = (
            "【查询结果】\n"
            f"状态: {status}\n"
            f"服务器IP: {ip}\n"
            f"版本: {version}\n"
            f"MOTD: {motd}"
            f"玩家人数: {players}\n"
            f"在线玩家: \n{name_list_str}"
        )

        return CommandResult().message(result_text).use_t2i(False)

    @filter.command("一言")
    async def hitokoto(self, message: AstrMessageEvent):
        """来一条一言"""
        url = "https://v1.hitokoto.cn"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return CommandResult().error("请求失败")
                data = await resp.json()
        return CommandResult().message(data["hitokoto"] + " —— " + data["from"])

    async def save_what_eat_data(self):
        path = os.path.abspath(os.path.dirname(__file__))
        with open(path + "/resources/food.json", "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"data": self.what_to_eat_data}, ensure_ascii=False, indent=2
                )
            )

    @filter.command("今天吃什么")
    async def what_to_eat(self, message: AstrMessageEvent):
        """今天吃什么"""
        if "添加" in message.message_str:
            l = message.message_str.split(" ")
            # 今天吃什么 添加 xxx xxx xxx
            if len(l) < 3:
                return CommandResult().error(
                    "格式：今天吃什么 添加 [食物1] [食物2] ..."
                )
            self.what_to_eat_data += l[2:]  # 添加食物
            await self.save_what_eat_data()
            return CommandResult().message("添加成功")
        elif "删除" in message.message_str:
            l = message.message_str.split(" ")
            # 今天吃什么 删除 xxx xxx xxx
            if len(l) < 3:
                return CommandResult().error(
                    "格式：今天吃什么 删除 [食物1] [食物2] ..."
                )
            for i in l[2:]:
                if i in self.what_to_eat_data:
                    self.what_to_eat_data.remove(i)
            await self.save_what_eat_data()
            return CommandResult().message("删除成功")

        ret = f"今天吃 {random.choice(self.what_to_eat_data)}！"
        return CommandResult().message(ret)

    @filter.command("喜加一")
    async def epic_free_game(self, message: AstrMessageEvent):
        """EPIC 喜加一"""
        url = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return CommandResult().error("请求失败")
                data = await resp.json()

        games = []
        upcoming = []

        for game in data["data"]["Catalog"]["searchStore"]["elements"]:
            title = game.get("title", "未知")
            try:
                if not game.get("promotions"):
                    continue
                original_price = game["price"]["totalPrice"]["fmtPrice"][
                    "originalPrice"
                ]
                discount_price = game["price"]["totalPrice"]["fmtPrice"][
                    "discountPrice"
                ]
                promotions = game["promotions"]["promotionalOffers"]
                upcoming_promotions = game["promotions"]["upcomingPromotionalOffers"]

                if promotions:
                    promotion = promotions[0]["promotionalOffers"][0]
                else:
                    promotion = upcoming_promotions[0]["promotionalOffers"][0]
                start = promotion["startDate"]
                end = promotion["endDate"]
                # 2024-09-19T15:00:00.000Z
                start_utc8 = datetime.datetime.strptime(
                    start, "%Y-%m-%dT%H:%M:%S.%fZ"
                ) + datetime.timedelta(hours=8)
                start_human = start_utc8.strftime("%Y-%m-%d %H:%M")
                end_utc8 = datetime.datetime.strptime(
                    end, "%Y-%m-%dT%H:%M:%S.%fZ"
                ) + datetime.timedelta(hours=8)
                end_human = end_utc8.strftime("%Y-%m-%d %H:%M")
                discount = float(promotion["discountSetting"]["discountPercentage"])
                if discount != 0:
                    # 过滤掉不是免费的游戏
                    continue

                if promotions:
                    games.append(
                        f"【{title}】\n原价: {original_price} | 现价: {discount_price}\n活动时间: {start_human} - {end_human}"
                    )
                else:
                    upcoming.append(
                        f"【{title}】\n原价: {original_price} | 现价: {discount_price}\n活动时间: {start_human} - {end_human}"
                    )

            except BaseException as e:
                raise e
                games.append(f"处理 {title} 时出现错误")

        if len(games) == 0:
            return CommandResult().message("暂无免费游戏")
        return (
            CommandResult()
            .message(
                "【EPIC 喜加一】\n"
                + "\n\n".join(games)
                + "\n\n"
                + "【即将免费】\n"
                + "\n\n".join(upcoming)
            )
            .use_t2i(False)
        )

    @filter.regex(r"^(早安|晚安)")
    async def good_morning(self, message: AstrMessageEvent):
        """和Bot说早晚安，记录睡眠时间，培养良好作息"""
        # CREDIT: 灵感部分借鉴自：https://github.com/MinatoAquaCrews/nonebot_plugin_morning
        umo_id = message.unified_msg_origin
        user_id = message.message_obj.sender.user_id
        user_name = message.message_obj.sender.nickname
        curr_utc8 = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        curr_human = curr_utc8.strftime("%Y-%m-%d %H:%M:%S")

        is_night = "晚安" in message.message_str

        if umo_id in self.good_morning_data:
            umo = self.good_morning_data[umo_id]
        else:
            umo = {}
        if user_id in umo:
            user = umo[user_id]
        else:
            user = {
                "daily": {
                    "morning_time": "",
                    "night_time": "",
                }
            }

        if is_night:
            user["daily"]["night_time"] = curr_human
            user["daily"]["morning_time"] = ""  # 晚安后清空早安时间
        else:
            user["daily"]["morning_time"] = curr_human

        umo[user_id] = user
        self.good_morning_data[umo_id] = umo

        with open(f"data/{self.PLUGIN_NAME}_data.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(self.good_morning_data, ensure_ascii=False, indent=2))

        # 根据 day 判断今天是本群第几个睡觉的
        # TODO: 此处可以缓存
        curr_day: int = curr_utc8.day
        curr_day_sleeping = 0
        for v in umo.values():
            if v["daily"]["night_time"] and not v["daily"]["morning_time"]:
                # he/she is sleeping
                user_day = datetime.datetime.strptime(
                    v["daily"]["night_time"], "%Y-%m-%d %H:%M:%S"
                ).day
                if user_day == curr_day:
                    # 今天睡觉的人数
                    curr_day_sleeping += 1

        if not is_night:
            # 计算睡眠时间: xx小时xx分
            # 此处可以联动 TODO
            sleep_duration_human = ""
            if user["daily"]["night_time"]:
                night_time = datetime.datetime.strptime(
                    user["daily"]["night_time"], "%Y-%m-%d %H:%M:%S"
                )
                morning_time = datetime.datetime.strptime(
                    user["daily"]["morning_time"], "%Y-%m-%d %H:%M:%S"
                )
                sleep_duration = (morning_time - night_time).total_seconds()
                hrs = int(sleep_duration / 3600)
                mins = int((sleep_duration % 3600) / 60)
                sleep_duration_human = f"{hrs}小时{mins}分"

            return (
                CommandResult()
                .message(
                    f"早安喵，{user_name}！\n现在是 {curr_human}，昨晚你睡了 {sleep_duration_human}。"
                )
                .use_t2i(False)
            )
        else:
            # 此处可以联动 TODO
            return (
                CommandResult()
                .message(
                    f"晚安喵，{user_name}！\n现在是 {curr_human}，你是本群今天第 {curr_day_sleeping} 个睡觉的。"
                )
                .use_t2i(False)
            )
