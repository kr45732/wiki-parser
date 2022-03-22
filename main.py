from werkzeug.exceptions import BadRequestKeyError
from flask import Flask, request
import dataclasses
import json
from typing import Any
import urllib.parse
import requests
import mwparserfromhell
from mwparserfromhell.nodes import Wikilink, Text, Template
import time
import threading


default_chest_costs = dict(
    Wood={7: 0},
    Gold={1: 25_000, 2: 50_000, 7: 100_000},
    Diamond={1: 50_000, 2: 100_000, 7: 250_000},
    Emerald={1: 100_000, 2: 250_000, 7: 500_000},
    Obsidian={1: 250_000, 2: 500_000, 7: 1_000_000},
    Bedrock={4: 4, 7: 2_000_000}
)


@dataclasses.dataclass
class DungeonDrop:
    item: str
    floor: int
    chest: str
    cost: int
    drop_chances: dict

    def get_drop_chance(self, has_s_plus: bool, talisman_level: int, boss_luck: int):
        drop_identifier = "S" + ("+" if has_s_plus else "") + "ABCD"[
            talisman_level] + str(len([i for i in [0, 1, 3, 5, 10] if i >= boss_luck]))
        return self.drop_chances.get(drop_identifier)


class ObjectEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if dataclasses.is_dataclass(o):
            return o.__dict__
        return super().default(o)


def romanToInt(num):
    roman_numerals = {'I': 1, 'V': 5, 'X': 10}
    result = 0
    for i, c in enumerate(num):
        if (i+1) == len(num) or roman_numerals[c] >= roman_numerals[num[i+1]]:
            result += roman_numerals[c]
        else:
            result -= roman_numerals[c]
    return result


def fetch_dungeon_loot():
    titles = [f"Template:Catacombs Floor {f} Loot" for f in [
        "I", "II", "III", "IV", "V", "VI", "VII"]]
    titles.extend([f"Template:Catacombs Floor {f} Loot Master" for f in [
                  "I", "II", "III", "IV", "V", "VI", "VII"]])
    items = {}
    for title, floor in get_wiki_sources_by_title(*titles).items():
        floor_num = -1
        floor_data = {}
        for template in floor.filter_templates():
            if template.name.strip() == "Dungeon Chest Table/Row":
                item = None
                ifloor = None
                chest = None
                cost = 0
                drop_chances = {}

                for param in template.params:
                    attr_name = param.name.nodes[0].strip()
                    attr_value = param.value.nodes[0].strip()
                    if attr_name == "item":
                        if item is None:
                            item = attr_value.replace(
                                "Ultimate_Jerry", "Ultimate Jerry").replace("’", "'")
                            if item.startswith("Wise "):
                                item = "Ultimate " + item
                            elif item.endswith(" Pet"):
                                item = item.split(" Pet")[0]
                    elif attr_name == "chest":
                        chest = attr_value
                    elif attr_name == "cost":
                        cost = int(attr_value)
                    elif attr_name == "floor":
                        ifloor = int(attr_value)
                        if title.endswith("Master"):
                            ifloor += 7
                        floor_num = ifloor
                    elif attr_name.startswith("S"):
                        drop_chances[attr_name] = attr_value
                if item is None or ifloor is None or chest is None:
                    print("WARNING: Missing data for item: " + str(template))
                else:
                    if cost == 0:
                        defaults = default_chest_costs[chest]
                        cost = defaults[min(
                            f for f in defaults.keys() if f >= (ifloor-7 if title.endswith("Master") else ifloor))]

                    if(chest not in floor_data.keys()):
                        floor_data[chest] = []
                    floor_data[chest].append(DungeonDrop(
                        item, ifloor, chest, cost, drop_chances))
        items[floor_num] = floor_data
    return items


def fetch_dragon_loot():
    titles = [f"Template:Dragon loot tables {f}" for f in [
        "superior", "strong", "unstable", "young", "wise", "old", "protector"]]
    items = {}
    for title, dragon in get_wiki_sources_by_title(*titles).items():
        cur_floor = {}
        cur_name = ""
        cur_item = {}
        for counter, template in enumerate(dragon.nodes):
            if type(template) == Wikilink:
                if not template.title.startswith("File"):
                    if cur_item != {}:
                        cur_floor[cur_name] = cur_item
                    cur_name = template.title.strip()
                    if dragon.nodes[counter-2] == "{{Legendary}}":
                        cur_name = f"Legendary {cur_name}"
                    elif dragon.nodes[counter-2] == "{{Epic}}":
                        cur_name = f"Epic {cur_name}"
                    if cur_name.endswith(" Pet"):
                        cur_name = cur_name.split(" Pet")[0]
                    cur_item = {}
                elif template.title.startswith("File:SkyBlock items summoning eye.png"):
                    cur_item["eye"] = True
            elif type(template) == Text:
                if template.value.strip() == "Unique":
                    cur_item["unique"] = True
                else:
                    try:
                        cur_item["quality"] = int(template.strip())
                    except ValueError:
                        pass
            elif type(template) == Template:
                if len(template.params) == 2 and template.params[0] == "green":
                    cur_item["drop_chance"] = template.params[1].value.strip()
        items[title.split("tables ")[1]] = cur_floor
    return items


def get_wiki_sources_by_title(*page_titles: str, wiki_host: str = "wiki.hypixel.net"):
    prepared_titles = "|".join(map(urllib.parse.quote, page_titles))
    api_data = requests.get(
        f"https://{wiki_host}/api.php?action=query&prop=revisions&titles={prepared_titles}&rvprop=content&format=json&rvslots=main").json()
    if "batchcomplete" not in api_data:
        print(f"Batch data not present in wiki response for: {page_titles}")

    return {
        page["title"]: mwparserfromhell.parse(
            page["revisions"][0]["slots"]["main"]["*"])
        for _, page in api_data["query"]["pages"].items()
    }


def update_data():
    dungeon_loot_data = fetch_dungeon_loot()
    with open("dungeon_loot.json", "w", encoding="utf-8") as f:
        json.dump(dungeon_loot_data, f, ensure_ascii=False,
                  indent=4, cls=ObjectEncoder)

    dragon_loot_data = fetch_dragon_loot()
    with open("dragon_loot.json", "w", encoding="utf-8") as f:
        json.dump(dragon_loot_data, f, ensure_ascii=False,
                  indent=4, cls=ObjectEncoder)


app = Flask("app")


@app.route("/")
def home():
    return {"deez": "nuts"}


@app.route("/dungeon_loot")
def dungeon_loot():
    args = request.args

    floor = 0
    try:
        floor = int(args["floor"])
    except (ValueError, BadRequestKeyError):
        pass
    if floor < 1 or floor > 14:
        return {"cause": "Invalid"}

    with open("dungeon_loot.json") as file:
        return json.load(file)[str(floor)]


@app.route("/dragon_loot")
def dragon_loot():
    with open("dragon_loot.json") as file:
        return json.load(file)


@app.before_first_request
def activate_job():
    def run_job():
        while True:
            print("Updating data")
            update_data()
            print("Data updated")
            time.sleep(3600)

    thread = threading.Thread(target=run_job)
    thread.start()


app.run(host="0.0.0.0", port=8081)
