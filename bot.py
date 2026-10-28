import random
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import xml.etree.ElementTree as ET
import json
from dotenv import load_dotenv
import os
import socket
import time
import re
import urllib.parse
from datetime import datetime
import asyncio
import aiosqlite  

# -------------------
# 1. setting n .env
# -------------------
load_dotenv()

UNDER_MAINTENANCE = False  # True -> maintenance
cachekill = False        # True -> init global cache 

TOKEN = os.getenv("TOKEN")

raw_dev_ids = os.getenv("DEVID", "")
DEV_IDS = {int(uid.strip()) for uid in raw_dev_ids.split(".") if uid.strip().isdigit()}

DB_NAME = "settings.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS "setting" (
                "UserID" TEXT NOT NULL,
                "AllowAI" INTEGER NOT NULL DEFAULT 0,
                "Language" TEXT NOT NULL DEFAULT 'en',
                PRIMARY KEY("UserID")
            )
        """)
        try:
            await db.execute("ALTER TABLE setting ADD COLUMN Language TEXT NOT NULL DEFAULT 'en'")
        except Exception:
            pass
        await db.commit()

def wait_for_internet():
    while True:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            print("Internet connection is successful! Start the bot!")
            break
        except OSError:
            print("Internet connection failed... retry in 5 seconds...")
            time.sleep(5)

# -------------------
# Localization (i18n) Setting
# -------------------
LOCALES = {}

def load_locales():
    locales_dir = "locales"
    if not os.path.exists(locales_dir):
        os.makedirs(locales_dir)
        
    for filename in os.listdir(locales_dir):
        if filename.endswith(".json"):
            lang_code = filename[:-5]  # 예: "en.json" -> "en"
            filepath = os.path.join(locales_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    LOCALES[lang_code] = json.load(f)
                print(f"[Localization] Loaded language file: {filename}")
            except Exception as e:
                print(f"[Localization Error] Failed to load {filename}: {e}")

async def get_user_lang(user_id: int) -> str:
    """유저의 언어 설정 가져오기 (기본값: en)"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT Language FROM setting WHERE UserID = ?", (str(user_id),)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                return row[0]
    return "en"

def t(lang: str, key: str, **kwargs) -> str:
    """번역 텍스트를 가져오고 f-string 포맷팅을 적용하는 헬퍼 함수"""
    lang_data = LOCALES.get(lang, LOCALES.get("en", {}))
    text = lang_data.get(key, LOCALES.get("en", {}).get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text

request_lock = asyncio.Lock()
last_request_time = 0.0

def safe_get(session: aiohttp.ClientSession, url: str, **kwargs):
    class SafeRequestContext:
        async def __aenter__(self):
            global last_request_time
            async with request_lock:
                elapsed = time.time() - last_request_time
                if elapsed < 0.6:
                    await asyncio.sleep(0.6 - elapsed)
                last_request_time = time.time()

            self.resp = await session.get(url, **kwargs)
            return self.resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await self.resp.__aexit__(exc_type, exc_val, exc_tb)

    return SafeRequestContext()

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://safebooru.org/",
}

# -------------------
# utility
# -------------------
LOGS_DIR = "logs"
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

BOOT_TIME_STR = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILENAME = os.path.join(LOGS_DIR, f"{BOOT_TIME_STR}.log")

def write_stat_log(user: discord.User | discord.Member, action_name: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} {user.name} ({user.id}): used command: {action_name}\n"
    try:
        with open(LOG_FILENAME, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"[Logging Error] {e}")

ZW_0 = "\u200b"
ZW_1 = "\u200c"

def hide_user_id(user_id: int) -> str:
    binary = bin(user_id)[2:]
    return "".join(ZW_1 if b == "1" else ZW_0 for b in binary)

def extract_hidden_user_id(text: str) -> int | None:
    hidden_bits = [c for c in text if c in (ZW_0, ZW_1)]
    if not hidden_bits:
        return None
    binary = "".join("1" if c == ZW_1 else "0" for c in hidden_bits)
    try:
        return int(binary, 2)
    except ValueError:
        return None

# -------------------
# 3. UI / View
# -------------------
intents = discord.Intents.default()

def clean_and_validate_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip().split()[0]
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        safe_path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/:@!$&'()*+,;=")
        safe_query = urllib.parse.quote(urllib.parse.unquote(parsed.query), safe="=&?:@!$'()*+,;/")
        encoded_url = urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, safe_path, parsed.params, safe_query, parsed.fragment
        ))
        return "" if re.search(r'\s', encoded_url) else encoded_url
    except Exception:
        return ""

def resolve_source_url(source: str) -> str:
    if not source:
        return ""
    source = source.strip()
    if "pximg.net" in source:
        match = re.search(r'(\d+)(?:_p\d+)?\.(?:jpg|png|gif)', source)
        if match:
            return f"https://www.pixiv.net/artworks/{match.group(1)}"
    if "illust_id=" in source:
        match = re.search(r'illust_id=(\d+)', source)
        if match:
            return f"https://www.pixiv.net/artworks/{match.group(1)}"
    if source.isdigit():
        return f"https://www.pixiv.net/artworks/{source}"
    url_match = re.search(r'https?://[^\s<>"]+|www\.[^\s<>"]+', source)
    if url_match:
        found_url = url_match.group(0)
        if found_url.startswith("www."):
            found_url = "https://" + found_url
        return clean_and_validate_url(found_url)
    return ""

class SettingsPanelView(discord.ui.View):
    def __init__(self, user_id: str, allow_ai: int, lang: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.allow_ai = allow_ai
        self.lang = lang
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        
        ai_label_key = "AI_ALLOW" if self.allow_ai == 1 else "AI_DISALLOW"
        ai_label = t(self.lang, ai_label_key)
        ai_style = discord.ButtonStyle.success if self.allow_ai == 1 else discord.ButtonStyle.danger
        
        ai_button = discord.ui.Button(label=ai_label, style=ai_style, custom_id="setting:toggle_ai")
        ai_button.callback = self.toggle_ai_callback
        self.add_item(ai_button)

    async def toggle_ai_callback(self, interaction: discord.Interaction):
        self.allow_ai = 0 if self.allow_ai == 1 else 1
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT INTO setting (UserID, AllowAI) VALUES (?, ?)
                ON CONFLICT(UserID) DO UPDATE SET AllowAI = ?
            """, (self.user_id, self.allow_ai, self.allow_ai))
            await db.commit()

        self.update_buttons()
        status_key = "AI_STATUS_ALLOW" if self.allow_ai == 1 else "AI_STATUS_DISALLOW"
        status_text = t(self.lang, status_key)
        await interaction.response.edit_message(
            content=t(self.lang, "SETTING_SAVED", status=status_text),
            view=self
        )

class PicDetailView(discord.ui.View):
    user_cooldowns: dict[int, float] = {}

    def __init__(self, post_id: int = None, source_url: str = None, lang: str = "en"):
        super().__init__(timeout=None)
        self.lang = lang
        
        if post_id:
            safebooru_url = f"https://safebooru.org/index.php?page=post&s=view&id={post_id}"
            self.add_item(discord.ui.Button(label=t(lang, "BTN_VIEW"), url=safebooru_url, row=1))
            
            resolved_source = resolve_source_url(source_url)
            if resolved_source:
                try:
                    self.add_item(discord.ui.Button(label=t(lang, "BTN_SOURCE"), url=resolved_source, row=1))
                except Exception:
                    pass
            else:
                self.add_item(discord.ui.Button(label=t(lang, "BTN_SOURCE"), style=discord.ButtonStyle.secondary, disabled=True, emoji="🚫", row=1))

        # OneMore 및 Info 버튼 라벨 다국어 적용
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "safebooru:onemore_v2":
                    item.label = t(lang, "BTN_ONE_MORE")
                elif item.custom_id == "safebooru:info_v2":
                    item.label = t(lang, "BTN_INFO")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_lang = await get_user_lang(interaction.user.id)
        self.lang = user_lang

        if UNDER_MAINTENANCE and interaction.user.id not in DEV_IDS:
            msg = t(user_lang, "MAINTENANCE")
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
            return False

        now = time.time()
        last_clicked = self.user_cooldowns.get(interaction.user.id, 0.0)
        cooldown_time = 3.0
        elapsed = now - last_clicked

        if elapsed < cooldown_time:
            retry_after = cooldown_time - elapsed
            msg = t(user_lang, "TOO_FAST", retry_after=retry_after)
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
            return False

        self.user_cooldowns[interaction.user.id] = now
        return True

    @discord.ui.button(label="OneMore", style=discord.ButtonStyle.success, custom_id="safebooru:onemore_v2", row=0)
    async def onemore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        write_stat_log(interaction.user, "Button: OneMore")
        await interaction.response.defer()
        tag_query = ""
        if interaction.message.embeds:
            desc = interaction.message.embeds[0].description or ""
            if ":" in desc:
                raw_tag = desc.split(":", 1)[1].strip()
                tag_query = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|~])", r"\1", raw_tag)
                
                is_none = any(tag_query == lang_data.get("IMG_NONE") for lang_data in LOCALES.values())
                if is_none:
                    tag_query = ""

        err_msg, new_embed, new_view = await fetch_safebooru_image(tag_query, user=interaction.user)
        if err_msg:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        await interaction.followup.send(embed=new_embed, view=new_view)

    @discord.ui.button(label="Info", style=discord.ButtonStyle.primary, custom_id="safebooru:info_v2", row=0)
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_lang = await get_user_lang(interaction.user.id)
        write_stat_log(interaction.user, "Button: Info")
        await interaction.response.defer(ephemeral=True)
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        footer_text = embed.footer.text if (embed and embed.footer) else ""
        
        post_id = None
        if "ID: " in footer_text:
            raw_id = footer_text.split("ID: ")[-1].strip()
            if raw_id.isdigit():
                post_id = raw_id

        if not post_id:
            await interaction.followup.send(t(user_lang, "IMG_CANNOT_IDENTIFY"), ephemeral=True)
            return

        post_url = f"https://safebooru.org/index.php?page=dapi&s=post&q=index&id={post_id}&json=1"
        comment_url = f"https://safebooru.org/index.php?page=dapi&s=comment&q=index&post_id={post_id}"

        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            async with safe_get(session, post_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send(t(user_lang, "IMG_COULD_NOT_LOAD"), ephemeral=True)
                    return
                post_data = await resp.json()

            if not post_data:
                await interaction.followup.send(t(user_lang, "IMG_COULD_NOT_FIND_SOURCE"), ephemeral=True)
                return

            post = post_data[0]
            comment_count = 0
            try:
                async with safe_get(session, comment_url, timeout=aiohttp.ClientTimeout(total=3)) as c_resp:
                    if c_resp.status == 200:
                        c_text = await c_resp.text()
                        c_root = ET.fromstring(c_text)
                        comment_count = len(c_root.findall("comment"))
            except Exception:
                comment_count = 0

            raw_tags = post.get("tags", "").strip().split()
            characters = []
            view_page_url = f"https://safebooru.org/index.php?page=post&s=view&id={post_id}"
            try:
                async with safe_get(session, view_page_url, timeout=aiohttp.ClientTimeout(total=4)) as page_resp:
                    if page_resp.status == 200:
                        html_text = await page_resp.text()
                        char_matches = re.findall(r'class="tag-type-character"[^>]*>.*?<a[^>]*>([^<]+)</a>', html_text, re.DOTALL)
                        if char_matches:
                            characters = [c.strip().replace(" ", "_") for c in char_matches if c.strip() and c.strip() != "?"]
            except Exception:
                pass

            if not characters and raw_tags:
                fallback_chars = [t_item for t_item in raw_tags if "(" in t_item and ")" in t_item and not any(t_item.endswith(ext) for ext in ["_(cosplay)", "_(style)"])]
                if fallback_chars:
                    characters = fallback_chars

        score = post.get("score", 0)
        rating_map = {"s": "Safe", "q": "Questionable", "e": "Explicit", "general": "General"}
        raw_rating = post.get("rating", "Unknown")
        rating = rating_map.get(raw_rating, raw_rating.capitalize())
        width = post.get("width", 0)
        height = post.get("height", 0)
        dimensions = f"{width} × {height}" if width and height else t(user_lang, "IMG_UNKNOWN")
        char_text = ", ".join(characters) if characters else f"{t(user_lang, 'IMG_UNKNOWN')} / {t(user_lang, 'IMG_NONE')}"
        all_tags = ", ".join(raw_tags) if raw_tags else t(user_lang, "IMG_NONE")
        if len(all_tags) > 1000:
            all_tags = all_tags[:1000] + t(user_lang, "IMG_TRUNCATED")

        info_embed = discord.Embed(title=t(user_lang, "IMG_DETAILS_TITLE", post_id=post_id), color=discord.Color.blue())
        info_embed.add_field(name=t(user_lang, "IMG_ID"), value=str(post_id), inline=True)
        info_embed.add_field(name=t(user_lang, "IMG_SCORE"), value=str(score), inline=True)
        info_embed.add_field(name=t(user_lang, "IMG_RATING"), value=rating, inline=True)
        info_embed.add_field(name=t(user_lang, "IMG_DIMENSIONS"), value=dimensions, inline=True)
        info_embed.add_field(name=t(user_lang, "IMG_COMMENTS"), value=str(comment_count), inline=True)
        info_embed.add_field(name=t(user_lang, "IMG_CHARACTERS"), value=f"`{char_text}`", inline=False)
        info_embed.add_field(name=t(user_lang, "IMG_TAGS"), value=f"```{all_tags}```", inline=False)

        await interaction.followup.send(embed=info_embed, ephemeral=True)

    @discord.ui.button(label="", emoji="🔖", style=discord.ButtonStyle.secondary, custom_id="safebooru:bookmark_v1", row=0)
    async def bookmark_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_lang = await get_user_lang(interaction.user.id)
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        
        if not embed:
            await interaction.response.send_message(t(user_lang, "BOOKMARK_NOT_FOUND"), ephemeral=True)
            return

        try:
            dm_channel = await interaction.user.create_dm()
            
            dm_view = discord.ui.View()
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.url:
                    dm_view.add_item(discord.ui.Button(label=item.label, url=item.url))

            await dm_channel.send(
                content=t(user_lang, "BOOKMARK_TITLE"), 
                embed=embed, 
                view=dm_view if dm_view.children else None
            )

            write_stat_log(interaction.user, "Button: Bookmark")
            await interaction.response.send_message(t(user_lang, "BOOKMARK_SENT"), ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message(t(user_lang, "BOOKMARK_DM_ERROR"), ephemeral=True)
        except Exception as e:
            print(f"[Bookmark Error] {e}")
            await interaction.response.send_message(t(user_lang, "BOOKMARK_ERROR"), ephemeral=True)

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="safebooru:delete_v1", row=0)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_lang = await get_user_lang(interaction.user.id)
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        footer_text = embed.footer.text if (embed and embed.footer) else ""

        requester_id = extract_hidden_user_id(footer_text)

        is_requester = (requester_id and interaction.user.id == requester_id)
        is_admin = interaction.user.guild_permissions.manage_messages if interaction.guild else False

        if is_requester or is_admin:
            write_stat_log(interaction.user, "Button: Delete Image")
            try:
                await interaction.message.delete()
            except discord.Forbidden:
                await interaction.response.send_message(t(user_lang, "DELETE_NO_PERMISSION"), ephemeral=True)
        else:
            await interaction.response.send_message(t(user_lang, "DELETE_ONLY_REQUESTER"), ephemeral=True)

class TagHintView(discord.ui.View):
    def __init__(self, suggested_tag: str, lang: str = "en"):
        super().__init__(timeout=60)
        self.suggested_tag = suggested_tag
        self.lang = lang
        self.update_button()

    def update_button(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.label = t(self.lang, "BTN_YES")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_lang = await get_user_lang(interaction.user.id)
        self.lang = user_lang
        if UNDER_MAINTENANCE and interaction.user.id not in DEV_IDS:
            await interaction.response.send_message(t(user_lang, "MAINTENANCE"), ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.success, emoji="✅")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_lang = await get_user_lang(interaction.user.id)
        button.disabled = True
        await interaction.response.edit_message(content=t(user_lang, "SEARCH_PREFIX", tag=self.suggested_tag), view=self)

        err_msg, embed, view = await fetch_safebooru_image(self.suggested_tag, user=interaction.user)
        if err_msg:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        await interaction.followup.send(embed=embed, view=view)

# -------------------
# 4. custom tree n bot setting
# -------------------
class MaintenanceTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_lang = await get_user_lang(interaction.user.id)
        if interaction.type == discord.InteractionType.autocomplete:
            return True

        valid_types = (
            discord.InteractionType.application_command,
            discord.InteractionType.component
        )
        if interaction.type in valid_types:
            if UNDER_MAINTENANCE and interaction.user.id not in DEV_IDS:
                msg = t(user_lang, "MAINTENANCE")
                if not interaction.response.is_done():
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.followup.send(msg, ephemeral=True)
                return False
            
        if interaction.type == discord.InteractionType.application_command:
            cmd_name = interaction.command.name if interaction.command else "unknown_command"
            write_stat_log(interaction.user, f"/{cmd_name}")

        return True

class RandomPickBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=[], 
            intents=intents,
            tree_cls=MaintenanceTree
        )

    async def setup_hook(self):
        load_locales()
        self.add_view(PicDetailView())
        await init_db()

bot = RandomPickBot()

# -------------------
# 5. booru
# -------------------
async def find_tag_hint(session: aiohttp.ClientSession, original_tag: str) -> str:
    if not original_tag:
        return ""

    target_tag = original_tag.strip().split()[0].lower()

    autocomplete_url = f"https://safebooru.org/autocomplete.php?q={urllib.parse.quote(target_tag)}"
    try:
        async with safe_get(session, autocomplete_url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if data and isinstance(data, list):
                    for item in data:
                        val = item.get("value") if isinstance(item, dict) else str(item)
                        if val and val.lower() != target_tag:
                            return val
    except Exception as e:
        print(f"[Hint Debug 1] autocomplete.php 실패: {e}")

    dapi_url = (
        "https://safebooru.org/index.php?page=dapi&s=tag&q=index"
        f"&name_pattern=%25{urllib.parse.quote(target_tag)}%25"
        "&orderby=count&limit=3"
    )
    try:
        async with safe_get(session, dapi_url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
            if resp.status == 200:
                xml_text = await resp.text()
                root = ET.fromstring(xml_text)
                for tag_elem in root.findall("tag"):
                    name = tag_elem.attrib.get("name", "")
                    count = int(tag_elem.attrib.get("count", 0))
                    if name and count > 0 and name.lower() != target_tag:
                        return name
    except Exception as e:
        print(f"[Hint Debug 2] Failed Tag DAPI: {e}")

    return ""

async def fetch_safebooru_image(tag_query: str, user: discord.User | discord.Member = None):
    user_lang = await get_user_lang(user.id) if user else "en"
    
    allow_ai = 0
    if user:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT AllowAI FROM setting WHERE UserID = ?", (str(user.id),)) as cursor:
                row = await cursor.fetchone()
                if row:
                    allow_ai = row[0]

    effective_tag_query = tag_query
    if allow_ai == 0:
        if effective_tag_query:
            effective_tag_query += " -ai-generated -ai_generated -rating:questionable"
        else:
            effective_tag_query = "-ai-generated -ai_generated -rating:questionable"

    count_url = f"https://safebooru.org/index.php?page=dapi&s=post&q=index&tags={urllib.parse.quote(effective_tag_query)}&limit=1"
    
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
        async with safe_get(session, count_url) as resp:
            if resp.status != 200:
                return t(user_lang, "SEARCH_FAILED_COUNT"), None, None
            xml_text = await resp.text()

        try:
            root = ET.fromstring(xml_text)
            total_count = int(root.attrib.get("count", 0))
        except Exception:
            return t(user_lang, "SEARCH_FAILED_XML"), None, None

        if total_count == 0:
            hint = await find_tag_hint(session, tag_query)
            if hint:
                hint_view = TagHintView(suggested_tag=hint, lang=user_lang)
                return t(user_lang, "SEARCH_DID_YOU_MEAN", hint=hint), None, hint_view
            return t(user_lang, "SEARCH_NO_RESULTS"), None, None

        limit = 5000
        max_offset = max(total_count - limit, 0)
        offset = random.randint(0, max_offset)

        json_url = f"https://safebooru.org/index.php?page=dapi&s=post&q=index&json=1&limit={limit}&offset={offset}&tags={urllib.parse.quote(effective_tag_query)}"
        async with safe_get(session, json_url) as resp:
            if resp.status != 200:
                return t(user_lang, "SEARCH_FAILED_JSON"), None, None
            text = await resp.text()
            if not text.strip().startswith("["):
                return t(user_lang, "SEARCH_INVALID_JSON"), None, None
            data = json.loads(text)

    if not data:
        return t(user_lang, "SEARCH_NO_VALID_IMAGES"), None, None

    valid_pics = [
        p for p in data 
        if p.get("image") and not p.get("image").lower().endswith(('.mp4', '.webm', '.zip'))
    ]

    if not valid_pics:
        return t(user_lang, "SEARCH_NO_VALID_IMAGES"), None, None

    pic = random.choice(valid_pics)
    directory = pic.get("directory")
    image = pic.get("image")
    post_id = pic.get("id")
    source_url = pic.get("source", "").strip()

    no_comma_tag = tag_query.replace(","," ")
    none_text = t(user_lang, "IMG_NONE")
    clean_tag = (
        discord.utils.escape_markdown(no_comma_tag) if no_comma_tag else none_text
    )

    image_url = f"https://safebooru.org/images/{directory}/{image}"
    image_url = urllib.parse.quote(image_url, safe=":/")

    cache_buster = int(time.time())
    image_url = f"{image_url}?cb={cache_buster}"

    embed = discord.Embed(title=t(user_lang, "RANDOM_TITLE"), description=t(user_lang, "TAG_LABEL", tag=clean_tag), color=discord.Color.random())
    embed.set_image(url=image_url)

    hidden_id_str = hide_user_id(user.id) if user else ""
    if user:
        prefix = t(user_lang, "REQUESTED_BY_PREFIX")
        divider = t(user_lang, "REQUESTED_BY_DIVIDER")
        requester_text = f"{prefix}{user.name}{hidden_id_str}{divider}"
    else:
        requester_text = ""
        
    embed.set_footer(text=f"{requester_text}ID: {post_id}")

    view = PicDetailView(post_id=post_id, source_url=source_url, lang=user_lang)
    return None, embed, view

async def tag_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    if not current.strip():
        return []

    tokens = current.replace(",", " ").split()
    target_token = tokens[-1].lower() if tokens else ""

    if len(target_token) < 2:
        return []

    choices = []
    url = f"https://safebooru.org/autocomplete.php?q={urllib.parse.quote(target_token)}"

    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=1.8)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data and isinstance(data, list):
                        for item in data[:10]:
                            if isinstance(item, dict):
                                raw_value = item.get("value") or item.get("label") or ""
                            else:
                                raw_value = item

                            clean_tag = re.sub(r'\s*\(\d+\)$', '', str(raw_value)).strip()
                            if not clean_tag:
                                continue

                            if len(tokens) > 1:
                                prefix = " ".join(tokens[:-1]) + " "
                                final_val = f"{prefix}{clean_tag}"
                            else:
                                final_val = clean_tag

                            choices.append(
                                app_commands.Choice(
                                    name=str(final_val)[:100],
                                    value=str(final_val)[:100]
                                )
                            )
    except Exception as e:
        print(f"[Autocomplete Error] {e}")
        return []

    return choices

# -------------------
# 6. commands n listeners
# -------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    print(f"[DEBUG] 현재 점검 모드: {UNDER_MAINTENANCE}")
    print(f"[DEBUG] 등록된 관리자 ID 목록: {DEV_IDS}")
    print("현재 봇이 설치된 서버 목록:")
    for guild in bot.guilds:
        print(f"- 서버 이름: {guild.name} (ID: {guild.id}) / 멤버 수: {guild.member_count}명")
    now = datetime.now()
    activity = discord.CustomActivity(name=f"Last Boot: {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC+9)")
    await bot.change_presence(status=discord.Status.online, activity=activity)

    try:
        if cachekill:
            app_id = bot.user.id
            all_global = await bot.tree.fetch_commands(guild=None)
            deleted_count = 0
            for cmd in all_global:
                await bot.http.delete_global_command(app_id, cmd.id)
                deleted_count += 1
            print(f"Deleted {deleted_count} global commands")

        synced = await bot.tree.sync()
        print(f"Global commands synced: {len(synced)}")
    except Exception as e:
        print("Error during global cache reset:", e)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    user_lang = await get_user_lang(interaction.user.id)
    if isinstance(error, app_commands.CommandOnCooldown):
        msg = t(user_lang, "TOO_FAST", retry_after=error.retry_after)
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    else:
        print(f"[Error] {error}")

@bot.tree.command(name="randompic", description="Random image with optional tag")
@app_commands.describe(tag="tag")
@app_commands.autocomplete(tag=tag_autocomplete)
@app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
async def randompic(interaction: discord.Interaction, tag: str = None):
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound:
        print("⚠️ Interaction expired.")
        return

    tag_query = tag.replace(",", " ").replace("  ", " ").strip() if tag else ""
    if tag and ("yaoi" in tag):
        await interaction.followup.send("NO.", ephemeral=True)
        return

    err_msg, embed, view = await fetch_safebooru_image(tag_query, user=interaction.user)
    
    if err_msg:
        await interaction.edit_original_response(content=err_msg, view=view)
        return

    await interaction.edit_original_response(embed=embed, view=view)

@bot.tree.command(name="randomemoji", description="Pick a random emoji from all bot servers")
@app_commands.describe(emoji_type="gif/pic")
async def randomemoji(interaction: discord.Interaction, emoji_type: str = None):
    user_lang = await get_user_lang(interaction.user.id)
    await interaction.response.defer()
    all_emojis = [e for guild in bot.guilds for e in guild.emojis]
    if not all_emojis:
        await interaction.followup.send(t(user_lang, "EMOJI_NO_EMOJIS"))
        return

    t_type = emoji_type.lower() if emoji_type else ""
    if t_type == "gif":
        all_emojis = [e for e in all_emojis if e.animated]
    elif t_type == "pic":
        all_emojis = [e for e in all_emojis if not e.animated]

    if not all_emojis:
        await interaction.followup.send(t(user_lang, "EMOJI_NOT_FOUND", type=t_type))
        return

    await interaction.followup.send(str(random.choice(all_emojis)))

@bot.tree.command(name="faq", description="Show me FAQ!")
async def faq(interaction: discord.Interaction):
    user_lang = await get_user_lang(interaction.user.id)
    embed = discord.Embed(title=t(user_lang, "FAQ_TITLE"), description=t(user_lang, "FAQ_DESC"), color=discord.Color.random())
    
    faq_pairs = [
        ("FAQ_Q1", "FAQ_A1"),
        ("FAQ_Q2", "FAQ_A2"),
        ("FAQ_Q3", "FAQ_A3"),
        ("FAQ_Q4", "FAQ_A4"),
        ("FAQ_Q5", "FAQ_A5"),
        ("FAQ_Q6", "FAQ_A6"),
    ]
    
    for q_key, a_key in faq_pairs:
        embed.add_field(name=f"Q. {t(user_lang, q_key)}", value=f"A. {t(user_lang, a_key)}", inline=False)
        
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="setting", description="Change the bot settings")
async def setting(interaction: discord.Interaction):
    user_id_str = str(interaction.user.id)
    user_lang = await get_user_lang(interaction.user.id)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT AllowAI FROM setting WHERE UserID = ?", (user_id_str,)) as cursor:
            row = await cursor.fetchone()
            current_val = row[0] if row else 0

    try:
        view = SettingsPanelView(user_id_str, current_val, user_lang)
        await interaction.response.send_message(
            content=t(user_lang, "SETTING_TITLE"), 
            view=view, 
            ephemeral=True
        )
    except Exception as e:
        print(f"[Setting Error] {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(t(user_lang, "SETTING_ERROR"), ephemeral=True)

@bot.tree.command(name="language", description="Change your preferred language")
@app_commands.describe(lang="Choose your language")
@app_commands.choices(lang=[
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="한국어 (Korean)", value="ko"),
    app_commands.Choice(name="日本語 (Japanese)", value="ja"),
    app_commands.Choice(name="NyanNyanMeow(CoolKittyPaw)", value="meow")
])
async def language(interaction: discord.Interaction, lang: str):
    user_id_str = str(interaction.user.id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO setting (UserID, Language) VALUES (?, ?)
            ON CONFLICT(UserID) DO UPDATE SET Language = ?
        """, (user_id_str, lang, lang))
        await db.commit()

    res_msg = t(lang,"LANGUAGE_SET")
    await interaction.response.send_message(res_msg, ephemeral=True)

@bot.tree.command(name="help", description="Show the commands")
async def help(interaction: discord.Interaction):
    user_lang = await get_user_lang(interaction.user.id)
    embed = discord.Embed(title=t(user_lang, "HELP_TITLE"), description=t(user_lang, "HELP_DESC"), color=discord.Color.random())
    
    commands_list = [
        ("help", "HELP_help"),
        ("language", "HELP_language"),
        ("faq", "HELP_faq"),
        ("randompic", "HELP_randompic"),
        ("randomemoji", "HELP_randomemoji"),
        ("setting", "HELP_setting")
    ]
    
    for command, desc in commands_list:
        embed.add_field(name=f"```/{command}```", value=f"{t(user_lang, desc)}", inline=False)
        
    await interaction.response.send_message(embed=embed)

wait_for_internet()
bot.run(TOKEN)
