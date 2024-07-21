import re
import os
import bs4
import json
import asyncio
import typing
import functools
import discord
import requests
import sqlite3
import hashlib
from discord.ext import tasks, commands

def md5(input_str: str) -> str:
    md5_hash = hashlib.md5(input_str.encode())
    return md5_hash.hexdigest()

# Connect to SQLite database (or create it if it doesn't exist)
conn: sqlite3.Connection = sqlite3.connect('data/known_ids.db')
cursor: sqlite3.Cursor = conn.cursor()

# Create a table with an indexed integer column
cursor.execute('''
CREATE TABLE IF NOT EXISTS known (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value INTEGER NOT NULL,
    url_hash TEXT NOT NULL
)
''')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_value ON known (value)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_url_hash ON known (url_hash)')

def is_id_known(value: int, url: str) -> bool:
    cursor.execute('SELECT 1 FROM known WHERE value = ? AND url_hash = ? LIMIT 1', (value, md5(url)))
    return cursor.fetchone() is not None

def insert_known_id(value: int, url: str) -> None:
    cursor.execute('INSERT INTO known (value, url_hash) VALUES (?, ?)', (value, md5(url)))
    conn.commit()

# discord config
CHANNEL_ID = os.getenv('DISCORD_CHANNEL_ID', '')
AUTH_TOKEN = os.getenv('DISCORD_AUTH_TOKEN', '')

# constraint config
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 60))
SCAN_LIMIT = int(os.getenv('SCAN_LIMIT', 60))

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0"}

class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        urls = os.getenv('SEARCH_URLS', '')
        if not urls:
          raise Exception("No SEARCH_URLS defined") 
        self.search_urls = urls.split()
        super().__init__(*args, **kwargs)

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

        self.chan = await self.fetch_channel(CHANNEL_ID)
        print(f'CHANNEL_ID = {CHANNEL_ID}')
        print(self.chan)

        self.bg_task.start()

    async def crawl_url(self, search_url: str):
        print(f'Searching {search_url}')

        req = requests.get(search_url, headers=HEADERS)
        if not req:
            print("failed to get initial ebay request ({0})".format(req.status_code))
            return

        soup = bs4.BeautifulSoup(req.text, "html.parser")
        new_data = []
        count = 0

        for e in soup.findAll("article", attrs={"class": "aditem"}):
            new_entry = {
                "id": e["data-adid"],
                "url": "https://www.kleinanzeigen.de" + e["data-href"]
            }

            # getting tags first to filter entries from searching people
            first_tag = True
            useless_entry = False
            tags_p = e.find("div", attrs={"class": "aditem-main--bottom"}).p
            if tags_p:
                for span in tags_p.findAll("span"):
                    if span.string == "Gesuch":
                        useless_entry = True
                        break
                    if first_tag:
                        first_tag = False
                        new_entry["tags"] = span.string
                    else:
                        new_entry["tags"] += ", " + span.string

            # getting title
            title_a = e.find("a", attrs={"class": "ellipsis"})
            if not title_a:
                print("no title for ebay article with url " + new_entry["url"])
                useless_entry = True
            else:
                if "WBS" in title_a.string:
                    useless_entry = True
                else:
                    new_entry["title"] = title_a.string

            if useless_entry:
                continue

            if count >= SCAN_LIMIT:
                break

            # getting thumbnail image
            imagebox = e.find("div", attrs={"class": "imagebox srpimagebox"})
            if not imagebox:
                print("no image for ebay article with url " + new_entry["url"])
            else:
                new_entry["img"] = imagebox.find("img")["src"]

            # getting description
            desc_p = e.find("p", attrs={"class": "aditem-main--middle--description"})
            if not desc_p:
                print("no description for ebay article with url " + new_entry["url"])
            else:
                new_entry["desc"] = desc_p.get_text().replace("#", "")

            # getting location
            loc_div = e.find("div", attrs={"class": "aditem-main--top--left"})
            if not loc_div:
                print("no location for ebay article with url " + new_entry["url"])
            else:
                new_entry["loc"] = clean_messy_string(loc_div.get_text())
                new_entry["loc"] = re.sub(r"\(.+", "", new_entry["loc"])

            # getting price
            price_p = e.find("p", attrs={"class": "aditem-main--middle--price-shipping--price"})
            if not price_p:
                print("no price for ebay article with url " + new_entry["url"])
            else:
                new_entry["price"] = clean_messy_string(price_p.get_text())

            current_id = int(new_entry["id"])

            if not is_id_known(current_id, search_url):
                embed = discord.Embed(
                    title=new_entry["title"],
                    url=new_entry["url"],
                    description=new_entry["desc"],
                    color=discord.Color.green()
                )
                if "img" in new_entry:
                    embed.set_image(url=new_entry["img"])
                if "price" in new_entry:
                    embed.add_field(name="Preis", value=new_entry["price"], inline=True)
                if "loc" in new_entry:
                    embed.add_field(name="Ort", value=new_entry["loc"], inline=True)
                if "tags" in new_entry:
                    embed.add_field(name="Tags", value=new_entry["tags"])
                await self.chan.send(embed=embed)
                insert_known_id(current_id, search_url)
                await asyncio.sleep(1)

            new_data.append(new_entry)

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def bg_task(self):
        print("Starting to crawl")
        await self.wait_until_ready()
        for search_url in self.search_urls:
            await self.crawl_url(search_url)


# clean those weird strings on some pages
def clean_messy_string(mess):
    return re.sub(r"^\s", "", re.sub(r"\s+", " ", mess.replace("\n", "")))

if __name__ == '__main__':
    client = MyClient(intents=discord.Intents.default())
    client.run(AUTH_TOKEN)
