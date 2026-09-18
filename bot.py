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

# -------------------
# 1. setting n .env
# -------------------
load_dotenv()

UNDER_MAINTENANCE = False  # True -> maintenance
cachekill = False          # True -> init global cache 

TOKEN = os.getenv("TOKEN")
GIPHY = os.getenv("GIPHY")

raw_dev_ids = os.getenv("DEVID", "")
DEV_IDS = {int(uid.strip()) for uid in raw_dev_ids.split(".") if uid.strip().isdigit()}

GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
GIPHY_RANDOM_URL = "https://api.giphy.com/v1/gifs/random"

def wait_for_internet():
    while True:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            print("Internet connection is successful! Start the bot!")
            break
        except OSError:
            print("Internet connection failed... retry in 5 seconds...")
            time.sleep(5)

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

# header
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://safebooru.org/",
}

# -------------------
# utility
# -------------------
BOOT_TIME_STR = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILENAME = f"{BOOT_TIME_STR}.log"

def write_stat_log(user: discord.User | discord.Member, action_name: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} {user.name} ({user.id}): used command: {action_name}\n"
    try:
        with open(LOG_FILENAME, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"[Logging Error] {e}")

# 영폭 문자(Zero-Width Character): \u200b (0), \u200c (1)
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
# 3. UI 및 뷰 클래스
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

class PicDetailView(discord.ui.View):
    user_cooldowns: dict[int, float] = {}

    def __init__(self, post_id: int = None, source_url: str = None):
        super().__init__(timeout=None)
        if post_id:
            safebooru_url = f"https://safebooru.org/index.php?page=post&s=view&id={post_id}"
            self.add_item(discord.ui.Button(label="View", url=safebooru_url, row=1))
            
            resolved_source = resolve_source_url(source_url)
            if resolved_source:
                try:
                    self.add_item(discord.ui.Button(label="Source", url=resolved_source, row=1))
                except Exception:
                    pass
            else:
                self.add_item(discord.ui.Button(label="Source", style=discord.ButtonStyle.secondary, disabled=True, emoji="🚫", row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if UNDER_MAINTENANCE and interaction.user.id not in DEV_IDS:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, the service is under maintenance.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Sorry, the service is under maintenance.",
                    ephemeral=True
                )
            return False

        now = time.time()
        last_clicked = self.user_cooldowns.get(interaction.user.id, 0.0)
        cooldown_time = 3.0
        elapsed = now - last_clicked

        if elapsed < cooldown_time:
            retry_after = cooldown_time - elapsed
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"⏳ Too Fast! Try again in **{retry_after:.1f}** second.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"⏳ Too Fast! Try again in **{retry_after:.1f}** second.",
                    ephemeral=True
                )
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
            if desc.startswith("Tag: "):
                tag_query = desc.replace("Tag: ", "").strip()
                if tag_query == "None":
                    tag_query = ""

        err_msg, new_embed, new_view = await fetch_safebooru_image(tag_query, user=interaction.user)
        if err_msg:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        await interaction.followup.send(embed=new_embed, view=new_view)

    @discord.ui.button(label="Info", style=discord.ButtonStyle.primary, custom_id="safebooru:info_v2", row=0)
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            await interaction.followup.send("⚠️ Cannot identify Image", ephemeral=True)
            return

        post_url = f"https://safebooru.org/index.php?page=dapi&s=post&q=index&id={post_id}&json=1"
        comment_url = f"https://safebooru.org/index.php?page=dapi&s=comment&q=index&post_id={post_id}"

        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            async with safe_get(session, post_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("⚠️ Could not load data", ephemeral=True)
                    return
                post_data = await resp.json()

            if not post_data:
                await interaction.followup.send("⚠️ Could not find the source", ephemeral=True)
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
                fallback_chars = [t for t in raw_tags if "(" in t and ")" in t and not any(t.endswith(ext) for ext in ["_(cosplay)", "_(style)"])]
                if fallback_chars:
                    characters = fallback_chars

        score = post.get("score", 0)
        rating_map = {"s": "Safe", "q": "Questionable", "e": "Explicit", "general": "General"}
        raw_rating = post.get("rating", "Unknown")
        rating = rating_map.get(raw_rating, raw_rating.capitalize())
        width = post.get("width", 0)
        height = post.get("height", 0)
        dimensions = f"{width} × {height}" if width and height else "Unknown"
        char_text = ", ".join(characters) if characters else "Unknown / None"
        all_tags = ", ".join(raw_tags) if raw_tags else "None"
        if len(all_tags) > 1000:
            all_tags = all_tags[:1000] + "... (truncated)"

        info_embed = discord.Embed(title=f"ℹ️ Post Details — #{post_id}", color=discord.Color.blue())
        info_embed.add_field(name="🆔 ID", value=str(post_id), inline=True)
        info_embed.add_field(name="⭐ Score", value=str(score), inline=True)
        info_embed.add_field(name="🔞 Rating", value=rating, inline=True)
        info_embed.add_field(name="📐 Dimensions", value=dimensions, inline=True)
        info_embed.add_field(name="💬 Comments", value=str(comment_count), inline=True)
        info_embed.add_field(name="👤 Characters", value=f"`{char_text}`", inline=False)
        info_embed.add_field(name="🏷️ Tags", value=f"```{all_tags}```", inline=False)

        await interaction.followup.send(embed=info_embed, ephemeral=True)

    @discord.ui.button(label="Bookmark", emoji="🔖", style=discord.ButtonStyle.secondary, custom_id="safebooru:bookmark_v1", row=0)
    async def bookmark_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        
        if not embed:
            await interaction.response.send_message("⚠️ Could not find an image to save.", ephemeral=True)
            return

        try:
            dm_channel = await interaction.user.create_dm()
            
            dm_view = discord.ui.View()
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.url:
                    dm_view.add_item(discord.ui.Button(label=item.label, url=item.url))

            await dm_channel.send(
                content="🔖 **Safebooru Bookmarks**", 
                embed=embed, 
                view=dm_view if dm_view.children else None
            )

            write_stat_log(interaction.user, "Button: Bookmark")
            await interaction.response.send_message("📬 Image sent to your DMs!", ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Unable to send a DM. Please make sure **'Direct Messages'** from server members is enabled in your server privacy settings.",
                ephemeral=True
            )
        except Exception as e:
            print(f"[Bookmark Error] {e}")
            await interaction.response.send_message("⚠️ An error occurred while sending the message.", ephemeral=True)

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="safebooru:delete_v1", row=0)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
                await interaction.response.send_message(
                    "⚠️ The bot is not in this server, lacking permission to delete messages.", 
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "🚫 Only the user who requested this can remove this!",
                ephemeral=True
            )

class TagHintView(discord.ui.View):
    def __init__(self, suggested_tag: str):
        super().__init__(timeout=60)
        self.suggested_tag = suggested_tag

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if UNDER_MAINTENANCE and interaction.user.id not in DEV_IDS:
            await interaction.response.send_message(
                "Sorry, the service is under maintenance.", 
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="YES", style=discord.ButtonStyle.success, emoji="✅")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        await interaction.response.edit_message(content=f"🔎 Searching for **`{self.suggested_tag}`**...", view=self)

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
        if interaction.type == discord.InteractionType.autocomplete:
            return True

        valid_types = (
            discord.InteractionType.application_command,
            discord.InteractionType.component
        )
        if interaction.type in valid_types:
            if UNDER_MAINTENANCE and interaction.user.id not in DEV_IDS:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Sorry, the service is under maintenance.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Sorry, the service is under maintenance.",
                        ephemeral=True
                    )
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
        self.add_view(PicDetailView())

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
        print(f"[Hint Debug 2] Tag DAPI 실패: {e}")

    return ""

async def fetch_safebooru_image(tag_query: str, user: discord.User | discord.Member = None):
    count_url = f"https://safebooru.org/index.php?page=dapi&s=post&q=index&tags={urllib.parse.quote(tag_query)}&limit=1"
    
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
        async with safe_get(session, count_url) as resp:
            if resp.status != 200:
                return "⚠️ Failed to get count", None, None
            xml_text = await resp.text()

        try:
            root = ET.fromstring(xml_text)
            total_count = int(root.attrib.get("count", 0))
        except Exception:
            return "⚠️ Failed to parse XML count", None, None

        tag_count = len([t for t in tag_query.split(" ") if t]) if tag_query else 0

        if total_count == 0:
            hint = await find_tag_hint(session, tag_query)
            if hint:
                hint_view = TagHintView(suggested_tag=hint)
                return f"⚠️ No results for that tag.\nDid you mean: **`{hint}`**?", None, hint_view
            return "⚠️ No results for that tag.", None, None

        limit = 5000
        max_offset = max(total_count - limit, 0)
        offset = random.randint(0, max_offset)

        json_url = f"https://safebooru.org/index.php?page=dapi&s=post&q=index&json=1&limit={limit}&offset={offset}&tags={urllib.parse.quote(tag_query)}"
        async with safe_get(session, json_url) as resp:
            if resp.status != 200:
                return "⚠️ Failed to load JSON", None, None
            text = await resp.text()
            if not text.strip().startswith("["):
                return "⚠️ Server returned invalid JSON", None, None
            data = json.loads(text)

    if not data:
        return "⚠️ No images found in this range", None, None

    pic = random.choice(data)
    directory = pic.get("directory")
    image = pic.get("image")
    post_id = pic.get("id")
    source_url = pic.get("source", "").strip()

    if not directory or not image:
        return "⚠️ Invalid image data", None, None

    image_url = f"https://safebooru.org/images/{directory}/{image}"
    embed = discord.Embed(title="🎨 Random Image!", description=f"Tag: {tag_query or 'None'}", color=discord.Color.random())
    embed.set_image(url=image_url)

    hidden_id_str = hide_user_id(user.id) if user else ""
    requester_text = f"Requested by {user.name}{hidden_id_str} | " if user else ""
    embed.set_footer(text=f"{requester_text}ID: {post_id}")

    view = PicDetailView(post_id=post_id, source_url=source_url)
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
    if isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Too Fast! Try again in **{error.retry_after:.1f}** second."
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
    await interaction.response.defer()
    all_emojis = [e for guild in bot.guilds for e in guild.emojis]
    if not all_emojis:
        await interaction.followup.send("⚠️ Bot has no custom emojis in any server.")
        return

    t = emoji_type.lower() if emoji_type else ""
    if t == "gif":
        all_emojis = [e for e in all_emojis if e.animated]
    elif t == "pic":
        all_emojis = [e for e in all_emojis if not e.animated]

    if not all_emojis:
        await interaction.followup.send(f"⚠️ No emojis found for type '{t}'")
        return

    await interaction.followup.send(str(random.choice(all_emojis)))

@bot.tree.command(name="faq", description="Show me FAQ!")
async def faq(interaction: discord.Interaction):
    faq_questions = {
        "What emojis are included in randomemoji?": "Only custom emojis from servers where the bot is present.",
        "Where do you get the images from?": "Safebooru. You can check the tags there.",
        "Who made this?": "AXF4",
        "What is the current version?": "v3.0.3",
        "How can I invite the bot?": "[👉 Click here to invite the bot!](https://discord.com/oauth2/authorize?client_id=1440352198709088306&permissions=4503739214129152&integration_type=0&scope=bot)",
        "Can I use this on my personal account?": "[👉 Click here to add to your account!](https://discord.com/oauth2/authorize?client_id=1440352198709088306)"
    }
    embed = discord.Embed(title="FAQ <a:mikupat:1441064448235274250>", description="FAQ. something about random.", color=discord.Color.random())
    for question, answer in faq_questions.items():
        embed.add_field(name=f"Q. {question}", value=f"A. {answer}", inline=False)
    await interaction.response.send_message(embed=embed)

wait_for_internet()
bot.run(TOKEN)
