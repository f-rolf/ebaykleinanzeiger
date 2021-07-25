import re
import bs4
import json
import asyncio
import discord
import requests

# discord config
CHANNEL_ID = INSERT CHANNEL ID HERE
AUTH_TOKEN = INSERT AUTH TOKEN HERE

# url to scan
SEARCH_URL_EBAY = "INSERT URL TO SCAN HERE"

# constraint config
CHECK_INTERVAL = 60
SCAN_LIMIT = 10

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0"}


class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.first_scan = True
        self.crawl_task = self.loop.create_task(self.bg_task())

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def crawl_ebay(self):
        chan = self.get_channel(CHANNEL_ID)

        req = requests.get(SEARCH_URL_EBAY, headers=HEADERS)
        if not req:
            print("failed to get initial ebay request ({0})".format(req.status_code))
            return

        soup = bs4.BeautifulSoup(req.text, "html.parser")
        new_data = []
        count = 0

        for e in soup.findAll("article", attrs={"class": "aditem"}):
            new_entry = {
                "id": e["data-adid"],
                "url": "https://www.ebay-kleinanzeigen.de" + e["data-href"]
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
                print("no title for ebay article with url " + e["url"])
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
                print("no image for ebay article with url " + e["url"])
            else:
                new_entry["img"] = imagebox["data-imgsrc"]

            # getting description
            desc_p = e.find("p", attrs={"class": "aditem-main--middle--description"})
            if not desc_p:
                print("no description for ebay article with url " + e["url"])
            else:
                new_entry["desc"] = desc_p.string

            # getting location
            loc_div = e.find("div", attrs={"class": "aditem-main--top--left"})
            if not loc_div:
                print("no location for ebay article with url " + e["url"])
            else:
                new_entry["loc"] = clean_messy_string(loc_div.get_text())
                new_entry["loc"] = re.sub(r"\(.+", "", new_entry["loc"])

            # getting price
            price_p = e.find("p", attrs={"class": "aditem-main--middle--price"})
            if not price_p:
                print("no price for ebay article with url " + e["url"])
            else:
                new_entry["price"] = clean_messy_string(price_p.get_text())

            if not is_cached(new_entry["id"]) and not self.first_scan:
                embed = discord.Embed(
                    title="ebay: " + new_entry["title"],
                    url=new_entry["url"],
                    description=new_entry["desc"],
                    color=discord.Color.green()
                )
                if "price" in new_entry:
                    embed.add_field(name="Preis", value=new_entry["price"], inline=True)
                if "loc" in new_entry:
                    embed.add_field(name="Ort", value=new_entry["loc"], inline=True)
                if "tags" in new_entry:
                    embed.add_field(name="Tags", value=new_entry["tags"])
                if "img" in new_entry:
                    embed.set_image(url=new_entry["img"])
                await chan.send(embed=embed)
                await asyncio.sleep(1)

            new_data.append(new_entry)

        update_cache(new_data)

        if self.first_scan:
            self.first_scan = False

    async def bg_task(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await self.crawl_ebay()
            await asyncio.sleep(CHECK_INTERVAL)


# clean those weird strings on some pages
def clean_messy_string(mess):
    return re.sub(r"^\s", "", re.sub(r"\s+", " ", mess.replace("\n", "")))


# returns if the id string is found in the specified cache
def is_cached(id_string):
    with open("cache.json", "r") as cache_file:
        for entry in json.load(cache_file):
            if entry["id"] == id_string:
                return True
    return False


# write a cache to disk
def update_cache(new_data):
    with open("cache.json", "w") as cache_file:
        json.dump(new_data, cache_file)


if __name__ == '__main__':
    client = MyClient()
    client.run(AUTH_TOKEN)
