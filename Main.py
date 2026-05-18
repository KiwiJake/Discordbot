'''
===============================================================
 ██ ▄█▀ ██ ██     ██ ██      ██ ▄████▄ ██ ▄█▀ ██████ 
 ████   ██ ██ ▄█▄ ██ ██      ██ ██▄▄██ ████   ██▄▄   
 ██ ▀█▄ ██  ▀██▀██▀  ██   ████▀ ██  ██ ██ ▀█▄ ██▄▄▄▄ 
===============================================================
 File      : bot.py
 Project   : Code
 Author    : KIWI JAKE
 Created   : Sat May 16 2026
 Modified  : Sat May 16 2026
===============================================================
'''

import discord
from discord.ext import commands
from google import genai
from dotenv import load_dotenv
import os
from prompts import SYSTEM_PROMPT

load_dotenv()



DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
GEMINI = genai.Client(api_key=GEMINI_KEY)



intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.listen("on_message")
async def handle_mention(message):
    if message.author == bot.user:
        return
    
    if bot.user not in message.mentions:
        return
    
    prompt = (
        message.content
        .replace(f"<@{bot.user.id}>", "")
        .replace(f"<@!{bot.user.id}>", "")
        .strip()
    )

    if not prompt:
        await message.channel.send("Give me something for me to respond to :3")
        return

    try:
        response = GEMINI.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"system_instruction": SYSTEM_PROMPT}
        )

        text = response.text

        if len(text) <= 2000:
            await message.channel.send(text)
        else:
            chunks = [
                text[i:i+1999]
                for i in range(0, len(text), 1999)
            ]

            for chunk in chunks:
                await message.channel.send(chunk)

    except Exception as e:
        await message.channel.send(f"Error: {e}")


bot.run(DISCORD_TOKEN)