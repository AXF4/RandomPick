import random
import discord
from discord.ext import commands
from discord import app_commands
import nltk
from nltk.corpus import wordnet
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

def wait_for_internet():
    while True:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            print("Internet connection is successful! Start the bot!")
            break
        except OSError:
            print("Internet connection failed... retry in 5 seconds...")
            time_interval = 5
            time.sleep(time_interval)


# WordNet download
nltk.download('wordnet')

# Discord intents
intents = discord.Intents.default()

# bot class
class RandomPickBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

bot = RandomPickBot()

# get wordnet wordlist 
WORD_LIST = list({lemma.name() for syn in wordnet.all_synsets() for lemma in syn.lemmas()})
print(f"Word list loaded: {len(WORD_LIST)} words")

class WordQuizView(discord.ui.View):
    def __init__(self, options, correct_word, definition, header="", timeout=30):
        super().__init__(timeout=timeout)

        self.correct_word = correct_word
        self.definition = definition
        self.answered = False
        self.header = header

        for option in options:
            self.add_item(QuizButton(option, correct_word, self))

    async def on_timeout(self):
        if self.answered:
            return

        self.answered = True

        for item in self.children:
            item.disabled = True

            if normalize(item.label) == normalize(self.correct_word):
                item.style = discord.ButtonStyle.success
            else:
                item.style = discord.ButtonStyle.danger

        await self.message.edit(
            content=f"{self.header}"
                    f"📖 Definition:\n{self.definition}\n\n"
                    "<:mikucry:1441064496041820221>\n"
                    f"Time's up!\nCorrect answer: **{self.correct_word}**",
            view=self
        )
class QuizButton(discord.ui.Button):
    def __init__(self, label, correct_word, parent_view):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.correct_word = correct_word
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.answered:
            return

        self.parent_view.answered = True

        for item in self.parent_view.children:
            item.disabled = True

            if normalize(item.label) == normalize(self.correct_word):
                item.style = discord.ButtonStyle.success
            else:
                item.style = discord.ButtonStyle.danger

        if normalize(self.label) == normalize(self.correct_word):
            result = "<:mikuwow:1441065277579198525>\n"
            f"You're Right! Correct answer: **{self.correct_word}**"
        else:
            result = (
                "<:mikucry:1441064496041820221>\n"
                f"It's Wrong... Correct answer: **{self.correct_word}**"
            )

        await interaction.response.edit_message(
            content=f"{self.parent_view.header}"
                    f"📖 Definition:\n{self.parent_view.definition}\n\n{result}",
            view=self.parent_view
        )

def split_tag_tokens(tag: str) -> list[str]:

    tag = tag.strip()
    tokens = []
    current = []
    in_paren = False

    for char in tag:
        if char == '(':
            in_paren = True
            current.append(char)
        elif char == ')':
            in_paren = False
            current.append(char)
        elif char == '_' and not in_paren:
            token = "".join(current).strip()
            if token:
                tokens.append(token)
            current = []
        else:
            current.append(char)

    last_token = "".join(current).strip()
    if last_token:
        tokens.append(last_token)

    return tokens

def generate_tag_candidates(tag: str) -> list[str]:
    tokens = split_tag_tokens(tag)
    n = len(tokens)
    if n <= 1:
        return []

    candidates = []
    for length in range(n - 1, 0, -1):
        left = "_".join(tokens[:length])
        if left and left not in candidates and left != tag:
            candidates.append(left)

        right = "_".join(tokens[n - length:])
        if right and right not in candidates and right != tag:
            candidates.append(right)

    return candidates

async def check_tag_exists(session: aiohttp.ClientSession, tag: str) -> bool:
    encoded_name = urllib.parse.quote(tag, safe="")
    
    url = f"https://safebooru.org/index.php?page=dapi&s=tag&q=index&name={encoded_name}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
            if resp.status != 200:
                return False
            xml_text = await resp.text()
            root = ET.fromstring(xml_text)
            
            for tag_elem in root.findall("tag"):
                name = tag_elem.attrib.get("name", "")
                count = int(tag_elem.attrib.get("count", 0))
                if name.lower() == tag.lower() and count > 0:
                    return True
            return False
    except Exception:
        return False

async def find_tag_hint(session: aiohttp.ClientSession, original_tag: str) -> str:
    target_tag = original_tag.split()[0] if original_tag else ""
    candidates = generate_tag_candidates(target_tag)

    for candidate in candidates:
        if await check_tag_exists(session, candidate):
            return candidate
    return ""

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
            parsed.scheme,
            parsed.netloc,
            safe_path,
            parsed.params,
            safe_query,
            parsed.fragment
        ))
        
        if re.search(r'\s', encoded_url):
            return ""

        return encoded_url
    except Exception:
        return ""

def resolve_source_url(source: str) -> str:
    if not source:
        return ""

    source = source.strip()

    # 1. pximg.net
    if "pximg.net" in source:
        match = re.search(r'(\d+)(?:_p\d+)?\.(?:jpg|png|gif)', source)
        if match:
            return f"https://www.pixiv.net/artworks/{match.group(1)}"

    # 2. illust_id= 
    if "illust_id=" in source:
        match = re.search(r'illust_id=(\d+)', source)
        if match:
            return f"https://www.pixiv.net/artworks/{match.group(1)}"

    # 3. id only
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
    def __init__(self, post_id: int = None, source_url: str = None):
        super().__init__(timeout=None)

        if post_id:
            safebooru_url = f"https://safebooru.org/index.php?page=post&s=view&id={post_id}"
            self.add_item(discord.ui.Button(label="View", url=safebooru_url))

            resolved_source = resolve_source_url(source_url)
            if resolved_source:
                try:
                    self.add_item(discord.ui.Button(label="Source", url=resolved_source))
                except Exception:
                    pass
            else:
                self.add_item(discord.ui.Button(
                    label="Source", 
                    style=discord.ButtonStyle.secondary, 
                    disabled=True, 
                    emoji="🚫"
                ))

    @discord.ui.button(label="Info", style=discord.ButtonStyle.primary, custom_id="safebooru:info_v2")
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        footer_text = embed.footer.text if (embed and embed.footer) else ""
        
        post_id = None
        if "ID: " in footer_text:
            raw_id = footer_text.split("ID: ")[-1].strip()
            if raw_id.isdigit():
                post_id = raw_id

        if not post_id:
            await interaction.followup.send("⚠️ 이미지를 식별할 수 없습니다.", ephemeral=True)
            return

        # 1. Safebooru Post
        post_url = f"https://safebooru.org/index.php?page=dapi&s=post&q=index&id={post_id}&json=1"
        comment_url = f"https://safebooru.org/index.php?page=dapi&s=comment&q=index&post_id={post_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(post_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("⚠️ 정보를 불러오지 못했습니다.", ephemeral=True)
                    return
                post_data = await resp.json()

            if not post_data:
                await interaction.followup.send("⚠️ 게시글 정보를 찾을 수 없습니다.", ephemeral=True)
                return

            post = post_data[0]

            # 2. (Safebooru comment API XML)
            comment_count = 0
            try:
                async with session.get(comment_url, timeout=aiohttp.ClientTimeout(total=3)) as c_resp:
                    if c_resp.status == 200:
                        c_text = await c_resp.text()
                        c_root = ET.fromstring(c_text)
                        comment_count = len(c_root.findall("comment"))
            except Exception:
                comment_count = 0

            # 3. character tags
            raw_tags = post.get("tags", "").strip().split()
            characters = []
            
            view_page_url = f"https://safebooru.org/index.php?page=post&s=view&id={post_id}"
            try:
                async with session.get(view_page_url, timeout=aiohttp.ClientTimeout(total=4)) as page_resp:
                    if page_resp.status == 200:
                        html_text = await page_resp.text()
                        char_matches = re.findall(r'class="tag-type-character"[^>]*>.*?<a[^>]*>([^<]+)</a>', html_text, re.DOTALL)
                        if char_matches:
                            characters = [c.strip().replace(" ", "_") for c in char_matches if c.strip() and c.strip() != "?"]
            except Exception:
                pass

            # if failed
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

        info_embed = discord.Embed(
            title=f"ℹ️ Post Details — #{post_id}",
            color=discord.Color.blue()
        )
        info_embed.add_field(name="🆔 ID", value=str(post_id), inline=True)
        info_embed.add_field(name="⭐ Score", value=str(score), inline=True)
        info_embed.add_field(name="🔞 Rating", value=rating, inline=True)
        info_embed.add_field(name="📐 Dimensions", value=dimensions, inline=True)
        info_embed.add_field(name="💬 Comments", value=str(comment_count), inline=True)
        info_embed.add_field(name="👤 Characters", value=f"`{char_text}`", inline=False)
        info_embed.add_field(name="🏷️ Tags", value=f"```{all_tags}```", inline=False)

        await interaction.followup.send(embed=info_embed, ephemeral=True)

    @discord.ui.button(label="OneMore", style=discord.ButtonStyle.success, custom_id="safebooru:onemore_v2")
    async def onemore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        tag_query = ""
        if interaction.message.embeds:
            desc = interaction.message.embeds[0].description or ""
            if desc.startswith("Tag: "):
                tag_query = desc.replace("Tag: ", "").strip()
                if tag_query == "None":
                    tag_query = ""

        err_msg, new_embed, new_view = await fetch_safebooru_image(tag_query)
        if err_msg:
            await interaction.followup.send(err_msg, ephemeral=True)
            return

        # 새 embed와 함께 갱신된 new_view를 전송
        await interaction.followup.send(embed=new_embed, view=new_view)

class RandomPickBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=[], intents=intents)

    async def setup_hook(self):
        # 재부팅 후에도 버튼 이벤트를 감지할 수 있도록 상시 등록
        self.add_view(PicDetailView())

bot = RandomPickBot()

def normalize(word):
    return word.replace("_", " ").replace("-", " ").lower().strip()

def get_syn_ant_hard(word):
    synsets = wordnet.synsets(word)
    if not synsets:
        return [], []

    syn = synsets[0]

    synonyms = set()
    antonyms = set()

    for lemma in syn.lemmas():
        name = lemma.name().replace("_", " ").replace("-", " ")

        if name != word:
            synonyms.add(name)

        for ant in lemma.antonyms():
            antonyms.add(
                ant.name().replace("_", " ").replace("-", " ")
            )

    return list(synonyms), list(antonyms)

# -------------------
# bot event
# -------------------
cachekill = False  # True -> init global cache

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    now = datetime.now()
    formatted_now = now.strftime("%Y-%m-%d %H:%M:%S")
    activity = discord.CustomActivity(name=f"Last Boot: {formatted_now} (UTC+9)")

    await bot.change_presence(status=discord.Status.online, activity=activity)

    try:
        if cachekill:
            app_id = bot.user.id  # bot app ID
            # get global command
            all_global = await bot.tree.fetch_commands(guild=None)
            
            deleted_count = 0
            for cmd in all_global:
                await bot.http.delete_global_command(app_id, cmd.id)
                deleted_count += 1
            print(f"Deleted {deleted_count} global commands")

        # global sync
        synced = await bot.tree.sync()
        print(f"Global commands synced: {len(synced)}")
        print("Commands:", [cmd.name for cmd in synced])

    except Exception as e:
        print("Error during global cache reset:", e)




# -------------------
# /picknumber
# -------------------
@bot.tree.command(name="picknumber", description="RandomNumberPicker")
@app_commands.describe(min="min", max="max")
async def picknumber(interaction: discord.Interaction, min: int, max: int):
    if min > max:
        await interaction.response.send_message("No.")
        return
    value = random.randint(min, max)
    await interaction.response.send_message(f"🎲 The Chosen one from {min} - {max}: **{value}**")

# -------------------
# /pickfloat
# -------------------
@bot.tree.command(name="pickfloat", description="RandomFloatPicker")
@app_commands.describe(min="min", max="max")
async def pickfloat(interaction: discord.Interaction, min: float, max: float):
    if min > max:
        await interaction.response.send_message("No.")
        return
    value = random.uniform(min, max)
    await interaction.response.send_message(f"🌊 The Chosen one from {min} - {max}: **{value}**")

# -------------------
# /pickword
# -------------------
@bot.tree.command(
    name="pickword",
    description="WordNet WordPicker"
)
async def pickword(interaction: discord.Interaction):
    #wait
    await interaction.response.defer()

    word = random.choice(WORD_LIST)

    # get meaning
    synsets = wordnet.synsets(word)
    definition = synsets[0].definition() if synsets else "IDK"

    await interaction.followup.send(f"📝 Word: **{word}**\nDefinition: {definition}")


#-------------------------
# wordquiz
#-------------------------
@bot.tree.command(
    name="wordquiz",
    description="Make Random English Quiz"
)
@app_commands.describe(
    mode="easy | normal | hard",
    choices="2..10 or hell"
)
@app_commands.choices(mode=[
    app_commands.Choice(name="easy", value="easy"),
    app_commands.Choice(name="normal", value="normal"),
    app_commands.Choice(name="hard", value="hard"),
])
async def wordquiz(
    interaction: discord.Interaction,
    mode: app_commands.Choice[str] = None,
    choices: str = None
):

    mode_value = mode.value if mode else "easy"

    # choices
    hell_mode = False

    if choices is None:
        choice_count = 3

    elif choices.lower() == "hell":
        hell_mode = True
        choice_count = None

    else:
        if not choices.isdigit():
            await interaction.response.send_message("Invalid choices value.")
            return

        choice_count = int(choices)

        if choice_count < 2 or choice_count > 10:
            await interaction.response.send_message("Choices must be between 2 and 10.")
            return

    # hell works only in hard
    if hell_mode and mode_value != "hard":
        await interaction.response.send_message(
            "Hell only sleeps in **HARD** places..."
        )
        return

    correct_word = random.choice(WORD_LIST)
    synsets = wordnet.synsets(correct_word)

    if not synsets:
        await interaction.response.send_message("Failed to get word.")
        return

    definition = synsets[0].definition()
    correct_pos = synsets[0].pos()

    wrong_words = []

    # --------------------
    # EASY
    # --------------------
    if mode_value == "easy":

        wrong_needed = (choice_count - 1) if not hell_mode else 2

        while len(wrong_words) < wrong_needed:
            w = random.choice(WORD_LIST)
            if w != correct_word and w not in wrong_words:
                wrong_words.append(w)

    # --------------------
    # NORMAL
    # --------------------
    elif mode_value == "normal":

        same_pos_words = []

        for w in WORD_LIST:
            if w == correct_word:
                continue

            syns = wordnet.synsets(w)
            if not syns:
                continue

            if syns[0].pos() != correct_pos:
                continue

            # noun -> filter proper noun
            if correct_pos == 'n':
                if correct_word[0].isupper():
                    if not w[0].isupper():
                        continue
                else:
                    if w[0].isupper():
                        continue

            same_pos_words.append(w)

        wrong_needed = choice_count - 1

        if len(same_pos_words) < wrong_needed:
            await interaction.response.send_message("Not enough same POS words.")
            return

        wrong_words = random.sample(same_pos_words, wrong_needed)

    # --------------------
    # HARD
    # --------------------
    elif mode_value == "hard":

        # Hard words candidates
        while True:
            candidate = random.choice(WORD_LIST)
            synsets = wordnet.synsets(candidate)

            if not synsets:
                continue

            syn = synsets[0]

            # no proper nouns
            if syn.instance_hypernyms():
                continue

            definition = syn.definition()
            syns, ants = get_syn_ant_hard(candidate)

            # normalize
            normalized_seen = set()
            pool = []

            for w in syns + ants:
                n = normalize(w)

                if n == normalize(candidate):
                    continue

                if n in normalized_seen:
                    continue

                normalized_seen.add(n)
                pool.append(w)

            # hell 
            if hell_mode:
                if len(pool) < 1:
                    continue

                correct_word = candidate
                break

            # just hard
            else:
                if len(pool) >= (choice_count - 1):
                    correct_word = candidate
                    break


        # hell mode
        if hell_mode:

            min_choices = 20   # Hell min choices

            # pool = syn + ant
            normalized_seen = set()
            pool = []

            for w in syns + ants:
                n = normalize(w)

                if n == normalize(correct_word):
                    continue

                if n in normalized_seen:
                    continue

                normalized_seen.add(n)
                pool.append(w)

            # if lacking
            if len(pool) < min_choices - 1:

                same_pos_words = []

                for w in WORD_LIST:
                    if w == correct_word:
                        continue

                    synsets_w = wordnet.synsets(w)
                    if not synsets_w:
                        continue

                    if synsets_w[0].pos() != syn.pos():
                        continue

                    n = normalize(w)

                    if n == normalize(correct_word):
                        continue

                    if n in normalized_seen:
                        continue

                    same_pos_words.append(w)

                random.shuffle(same_pos_words)

                for w in same_pos_words:
                    if len(pool) >= min_choices - 1:
                        break

                    n = normalize(w)
                    normalized_seen.add(n)
                    pool.append(w)
                else:
                    while len(pool) < min_choices - 1:
                        w = random.choice(WORD_LIST)
                        n = normalize(w)
                        if n==normalize(correct_word):
                            continue
                        if n==normalized_seen:
                            continue
                        if n in pool:
                            continue
                        if w in pool:
                            continue
                        pool.append(w)



            correct_word = candidate
            choices_list = pool + [correct_word]
            random.shuffle(choices_list)

            view = WordQuizView(choices_list, correct_word, definition)

            message = (
                "⚠️ **Caution!** Hard mode will likely present problems that rely solely on luck to solve.\n\n"
                f"📖 Definition:\n{definition}\n\n"
                f"🔥 Hell Mode Activated\n"
                f"⏳ You have 30 seconds!"
            )

            await interaction.response.send_message(content=message, view=view)
            view.message = await interaction.original_response()
            return

        # --------------------
        # just hard (2~10)
        # --------------------
        wrong_words = random.sample(pool, choice_count - 1)

    # --------------------
    # selections
    # --------------------
    if not hell_mode:
        choices_list = wrong_words + [correct_word]
        random.shuffle(choices_list)

    view = WordQuizView(choices_list, correct_word, definition)

    if mode_value == "hard":
        message = (
            "⚠️ **Caution!** Hard mode will likely present problems that rely solely on luck to solve.\n\n"
            f"📖 Definition:\n{definition}\n\n"
            f"⏳ You have 30 seconds!"
        )
    else:
        message = (
            f"📖 Definition:\n{definition}\n\n"
            f"⏳ You have 30 seconds!"
        )

    await interaction.response.send_message(content=message, view=view)
    view.message = await interaction.original_response()

#randompic
async def fetch_safebooru_image(tag_query: str):
    count_url = (
        "https://safebooru.org/index.php?page=dapi&s=post&q=index"
        f"&tags={urllib.parse.quote(tag_query)}"
        "&limit=1"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(count_url) as resp:
            if resp.status != 200:
                return "⚠️ Failed to get count", None, None
            xml_text = await resp.text()

        try:
            root = ET.fromstring(xml_text)
            total_count = int(root.attrib.get("count", 0))
        except Exception:
            return "⚠️ Failed to parse XML count", None, None

        tag_count = len([t for t in tag_query.split(" ") if t]) if tag_query else 0
        if tag_count >= 2 and total_count <= 10:
            return "NO.", None, None

        if total_count == 0:
            hint = await find_tag_hint(session, tag_query)
            if hint:
                return f"⚠️ No results for that tag.\nDid you mean: **`{hint}`**?", None, None
            return "⚠️ No results for that tag", None, None

        limit = 5000
        max_offset = max(total_count - limit, 0)
        offset = random.randint(0, max_offset)

        json_url = (
            "https://safebooru.org/index.php?page=dapi&s=post&q=index"
            f"&json=1&limit={limit}&offset={offset}"
            f"&tags={urllib.parse.quote(tag_query)}"
        )

        async with session.get(json_url) as resp:
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
    tags = pic.get("tags", "")

    if not directory or not image:
        return "⚠️ Invalid image data", None, None

    image_url = f"https://safebooru.org/images/{directory}/{image}"

    # fetch_safebooru_image 내부 embed 생성 부분:
    embed = discord.Embed(
        title="🎨 Random Image!",
        description=f"Tag: {tag_query or 'None'}",
        color=discord.Color.random()
    )
    embed.set_image(url=image_url)
    
    # footer에 태그 전체를 넣지 않고, ID만 깔끔하게 표시
    embed.set_footer(text=f"ID: {post_id}")

    view = PicDetailView(post_id=post_id, source_url=source_url)
    return None, embed, view

@bot.tree.command(
    name="randompic",
    description="Random image with optional tag"
)
@app_commands.describe(tag="tag")
async def randompic(interaction: discord.Interaction, tag: str = None):
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound:
        print("⚠️ Interaction expired (timed out before defer could be sent).")
        return
    if tag:
        tag_query = tag.replace(",", " ").replace("  ", " ").strip()
    else:
        tag_query = ""

    if tag and (":" in tag or "yaoi" in tag):
        await interaction.followup.send("NO.")
        return
    err_msg, embed, view = await fetch_safebooru_image(tag_query)
    if err_msg:
        await interaction.followup.send(err_msg)
        return

    await interaction.followup.send(embed=embed, view=view)



# randomemoji

@bot.tree.command(
    name="randomemoji",
    description="Pick a random emoji from all bot servers"
)
@app_commands.describe(
    emoji_type="gif/pic"  # gif = animated, pic = static
)
async def randomemoji(interaction: discord.Interaction, emoji_type: str = None):
    await interaction.response.defer()

    # assemble all custom emojis
    all_emojis = []
    for guild in bot.guilds:
        all_emojis.extend(guild.emojis)

    if not all_emojis:
        await interaction.followup.send("⚠️ Bot has no custom emojis in any server.")
        return

    # type filter
    t = emoji_type.lower() if emoji_type else ""
    if t == "gif":
        all_emojis = [e for e in all_emojis if e.animated]
    elif t == "pic":
        all_emojis = [e for e in all_emojis if not e.animated]

    if not all_emojis:
        await interaction.followup.send(f"⚠️ No emojis found for type '{t}'")
        return

    emoji = random.choice(all_emojis)
    await interaction.followup.send(f"{str(emoji)}")

#testpercent

@bot.tree.command(
    name="testpercent",
    description="Test success chance by percent"
)
@app_commands.describe(percent="Success probability (0~100)")
async def testpercent(interaction: discord.Interaction, percent: float):
    if percent < 0 or percent > 100:
        await interaction.response.send_message("❌ Percent must be between 0 and 100")
        return

    roll = random.uniform(0, 100)
    if roll < percent:
        await interaction.response.send_message(f"Success! ({percent}% chance)")
        await interaction.followup.send("<:mikuwow:1441065277579198525>")
    else:
        await interaction.response.send_message(f"Failed... ({percent}% chance)")
        await interaction.followup.send("<:mikucry:1441064496041820221> ")

#FAQ

@bot.tree.command(
    name="faq",
    description="Show me FAQ!"
)
@app_commands.describe()
async def faq(interaction: discord.Interaction):
    faq_questions = {
        "What Emojis are in randomemoji?" : "Only custom emojis that the bot involved in the guild.",
        "Where do you pick images from?" : "Safebooru. Check the tag from there."
    }

    embed = discord.Embed(
        title="FAQ <a:mikupat:1441064448235274250>",
        description=f"FAQ. something about random.",
        color=discord.Color.random()
    )

    for question, answer in faq_questions.items():
        embed.add_field(
            name=f"Q. {question}",
            value=f"A. {answer}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(
    name="randomgif",
    description="Random GIF from GIPHY"
)
@app_commands.describe(search="Search keyword (optional)")
async def randomgif(interaction: discord.Interaction, search: str = None):
    await interaction.response.defer()

    rating = "pg-13"

    async with aiohttp.ClientSession() as session:

        # =====================================================
        # if search
        # =====================================================
        if search:
            try:
                # check total
                params = {
                    "api_key": GIPHY,
                    "q": search,
                    "limit": 1,
                    "rating": rating
                }

                async with session.get(GIPHY_SEARCH_URL, params=params) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(
                            f"⚠️ GIPHY search failed (HTTP {resp.status})"
                        )
                        return

                    data = await resp.json()

                total_count = data.get("pagination", {}).get("total_count", 0)

                # no search -> fallback
                if total_count == 0:
                    print("No search results. Falling back to random.")
                else:
                    # offset 최대 4999 제한
                    max_offset = min(total_count - 1, 4999)
                    random_offset = random.randint(0, max_offset)

                    params = {
                        "api_key": GIPHY,
                        "q": search,
                        "limit": 1,
                        "offset": random_offset,
                        "rating": rating
                    }

                    async with session.get(GIPHY_SEARCH_URL, params=params) as resp:
                        if resp.status != 200:
                            await interaction.followup.send(
                                f"⚠️ GIPHY search failed (HTTP {resp.status})"
                            )
                            return

                        data = await resp.json()

                    if data.get("data"):
                        gif_url = data["data"][0]["images"]["original"]["url"]

                        embed = discord.Embed(
                            title=f"🎬 Random GIF for '{search}'",
                            color=discord.Color.random()
                        )
                        embed.set_image(url=gif_url)

                        await interaction.followup.send(embed=embed)
                        return

            except Exception as e:
                print("Search error:", e)

        # =====================================================
        # 2️⃣ else
        # =====================================================
        try:
            params = {
                "api_key": GIPHY,
                "rating": rating
            }

            async with session.get(GIPHY_RANDOM_URL, params=params) as resp:
                if resp.status != 200:
                    await interaction.followup.send(
                        f"⚠️ GIPHY random failed (HTTP {resp.status})"
                    )
                    return

                data = await resp.json()

        except Exception as e:
            print("Random error:", e)
            await interaction.followup.send("⚠️ Unexpected error.")
            return

    gif_url = data.get("data", {}).get("images", {}).get("original", {}).get("url")

    if not gif_url:
        await interaction.followup.send("⚠️ Failed to retrieve GIF.")
        return

    embed = discord.Embed(
        title="🎲 Random GIF",
        color=discord.Color.random()
    )
    embed.set_image(url=gif_url)

    await interaction.followup.send(embed=embed)

# -------------------
# token.txt
# -------------------
load_dotenv()

wait_for_internet()

TOKEN = os.getenv("TOKEN")
GIPHY = os.getenv("GIPHY")

GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
GIPHY_RANDOM_URL = "https://api.giphy.com/v1/gifs/random"


bot.run(TOKEN)
