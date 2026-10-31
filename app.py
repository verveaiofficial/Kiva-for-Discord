import os
import threading
import urllib.parse
import urllib.request
import discord
from flask import Flask
from google import genai
from google.genai import types

app = Flask(__name__)

@app.route('/')
def home():
    return "Quix Bot is online!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
TOKEN = os.environ.get("DISCORD_TOKEN")

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""
KB_BUCKET = "kb"
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "50"))

prompt_cache = None

def read_kb_file(name):
    url = f"{SUPABASE_URL}/storage/v1/object/{KB_BUCKET}/{urllib.parse.quote(name)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")

def load_system_prompt():
    # Order: Luna.md (model instructions) -> instructions.md (Discord rules) -> knowledge.md
    global prompt_cache
    if prompt_cache is not None:
        return prompt_cache
    try:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL or SUPABASE_SERVICE_KEY is not set")
        luna = read_kb_file("Luna.md")
        knowledge = read_kb_file("knowledge.md")
        with open("instructions.md", "r", encoding="utf-8") as f:
            discord_rules = f.read()
    except Exception as e:
        print(f"Prompt load failed: {type(e).__name__}: {e}")
        return None
    prompt_cache = f"{luna}\n\n{discord_rules}\n\nCustom Knowledge Base:\n{knowledge}"
    print("System prompt loaded.")
    return prompt_cache

def clean_mentions(text, bot_id):
    return text.replace(f'<@!{bot_id}>', '').replace(f'<@{bot_id}>', '').strip()

def author_label(m):
    return m.author.display_name or m.author.name

async def build_contents(channel, message, bot_id):
    # Pull recent channel messages so the bot sees what's going on, oldest first.
    history = []
    try:
        async for m in channel.history(limit=HISTORY_LIMIT, before=message):
            history.append(m)
    except Exception as e:
        print(f"History fetch failed: {type(e).__name__}: {e}")
    history.reverse()
    history.append(message)

    contents = []
    for m in history:
        text = clean_mentions(m.content or "", bot_id)
        if not text:
            if m is message:
                text = "(mentioned with no text)"
            else:
                continue
        if m.author.id == bot_id:
            role, line = "model", text
        else:
            role, line = "user", f"{author_label(m)}: {text}"
        # Gemini wants alternating turns, so merge back-to-back messages from the same side.
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n" + line
        else:
            contents.append({"role": role, "parts": [{"text": line}]})
    return contents

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class MyClient(discord.Client):
    async def on_ready(self):
        print(f'Logged on as {self.user}!')

    async def on_message(self, message):
        if message.author == self.user:
            return

        if self.user in message.mentions:
            system_prompt = load_system_prompt()
            if system_prompt is None:
                await message.reply("I can't load my instructions right now. Try again in a bit.")
                return

            try:
                # Async call keeps the bot responsive and fast
                contents = await build_contents(message.channel, message, self.user.id)
                response = await client.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.7
                    )
                )
                if response.text:
                    await message.reply(response.text)
                else:
                    await message.reply("Received an empty response.")
            except Exception as e:
                print(f"Generation error: {type(e).__name__}: {e}")
                await message.reply("Something went wrong. Try again.")

client_bot = MyClient(intents=intents)

if __name__ == '__main__':
    load_system_prompt()
    client_bot.run(TOKEN)
