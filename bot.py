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

# -------------------
# bot event
# -------------------
cachekill = False  # True -> init global cache

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

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

#randompic

@bot.tree.command(
    name="randompic",
    description="Random image with optional tag"
)
@app_commands.describe(tag="tag")
async def randompic(interaction: discord.Interaction, tag: str = None):
    await interaction.response.defer()

    if tag:
        tag_query = tag.replace(",", " ").replace("  ", " ").strip()
    else:
        tag_query = ""

    # Check for colon in tag
    if tag and ":" in tag:
        await interaction.followup.send("NO.")
        return

    # ----- (1) XML -> count -----
    count_url = (
        "https://safebooru.org/index.php?page=dapi&s=post&q=index"
        f"&tags={tag_query}"
        "&limit=1"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(count_url) as resp:
            if resp.status != 200:
                await interaction.followup.send("⚠️ Failed to get count")
                return
            xml_text = await resp.text()

    try:
        root = ET.fromstring(xml_text)
        total_count = int(root.attrib.get("count", 0))
    except:
        await interaction.followup.send("⚠️ Failed to parse XML count")
        return

    # If the user searched with 2 or more tags and the total results are
    # small (<= 20), refuse to respond with images.
    tag_count = len([t for t in tag_query.split(" ") if t]) if tag_query else 0
    if tag_count >= 2 and total_count <= 20:
        await interaction.followup.send("NO.")
        return

    if total_count == 0:
        await interaction.followup.send("⚠️ No results for that tag")
        return

    # ----- (2) offset range calc -----
    limit = 5000
    max_offset = max(total_count - limit, 0)
    offset = random.randint(0, max_offset)

    # ----- (3) JSON  -----
    json_url = (
        "https://safebooru.org/index.php?page=dapi&s=post&q=index"
        f"&json=1&limit={limit}&offset={offset}"
        f"&tags={tag_query}"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(json_url) as resp:
            if resp.status != 200:
                await interaction.followup.send("⚠️ Failed to load JSON")
                return

            text = await resp.text()

            # check JSON 
            if not text.strip().startswith("["):
                await interaction.followup.send("⚠️ Server returned invalid JSON")
                return

            data = json.loads(text)

    if not data:
        await interaction.followup.send("⚠️ No images found in this range")
        return

    # ----- (4) random choose -----
    pic = random.choice(data)

    directory = pic.get("directory")
    image = pic.get("image")

    if not directory or not image:
        await interaction.followup.send("⚠️ Invalid image data")
        return

    image_url = f"https://safebooru.org/images/{directory}/{image}"

    embed = discord.Embed(
        title="🎨 Random Image!",
        description=f"Tag: {tag or 'None'}",
        color=discord.Color.random()
    )
    embed.set_image(url=image_url)

    await interaction.followup.send(embed=embed)




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

    async with aiohttp.ClientSession() as session:

        # ----------------------------
        # if search
        # ----------------------------
        
        if search:
            params = {
                "api_key": GIPHY,
                "q": search,
                "limit": 25,
                "rating": "pg-13"
            }

            blocked_words = ["sex", "porn", "nude", "hentai"]

            if search and any(word in search.lower() for word in blocked_words):
                await interaction.followup.send("❌ That keyword is not allowed.")
                return


            async with session.get(GIPHY_SEARCH_URL, params=params) as resp:
                

                if resp.status != 200:
                    await interaction.followup.send(
                        f"⚠️ Search failed (HTTP {resp.status})"
                    )
                    return

                data = await resp.json()
                results = data.get("data", [])

                if results:
                    gif = random.choice(results)
                    gif_url = gif["images"]["original"]["url"]

                    embed = discord.Embed(
                        title=f"🎬 Random GIF for '{search}'",
                        color=discord.Color.random()
                    )
                    embed.set_image(url=gif_url)

                    await interaction.followup.send(embed=embed)
                    return

        # ----------------------------
        # no search
        # ----------------------------
        params = {
            "api_key": GIPHY,
            "rating": "pg-13"
        }

        async with session.get(GIPHY_RANDOM_URL, params=params) as resp:

            if resp.status != 200:
                await interaction.followup.send(
                    f"⚠️ GIPHY random failed (HTTP {resp.status})"
                )
                return

            data = await resp.json()

        gif_url = data["data"]["images"]["original"]["url"]

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
TOKEN = os.getenv("TOKEN")
GIPHY = os.getenv("GIPHY")

GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
GIPHY_RANDOM_URL = "https://api.giphy.com/v1/gifs/random"

bot.run(TOKEN)
