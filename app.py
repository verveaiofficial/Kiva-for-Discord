import os
import threading
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

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
TOKEN = os.environ.get("DISCORD_TOKEN")

try:
    with open("instructions.txt", "r", encoding="utf-8") as f:
        instructions = f.read()
except FileNotFoundError:
    instructions = "You are a helpful assistant."

try:
    with open("knowledge.txt", "r", encoding="utf-8") as f:
        knowledge = f.read()
except FileNotFoundError:
    knowledge = ""

bot_system_prompt = f"{instructions}\n\nCustom Knowledge Base:\n{knowledge}"

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
            user_message = message.content.replace(f'<@!{self.user.id}>', '').replace(f'<@{self.user.id}>', '').strip()
            
            try:
                # Async call keeps the bot responsive and fast
                response = await client.aio.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=user_message,
                    config=types.GenerateContentConfig(
                        system_instruction=bot_system_prompt,
                        temperature=0.7
                    )
                )
                if response.text:
                    await message.reply(response.text)
                else:
                    await message.reply("Received an empty response.")
            except Exception as e:
                print(f"Error details: {e}")
                await message.reply(f"Error: {e}")

client_bot = MyClient(intents=intents)

if __name__ == '__main__':
    client_bot.run(TOKEN)
