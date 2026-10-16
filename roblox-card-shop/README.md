# Card Shop Simulator (Roblox)

A pack-opening card collecting game for Roblox. Buy packs, pull creatures,
fill your binder, sell duplicates, and upgrade your shop.

All creatures are original. Don't add real Pokémon names or art, because
Roblox will take the game down.

## What's in version 1

- **3 packs**: Basic, Great and Ultra. Each has 5 cards with different rarity odds.
- **40 cards** in 5 rarities: Common, Uncommon, Rare, Holo and Secret. Any card has a 1% chance to be a **Shiny** worth 5x.
- **Pack reveal animation** that saves the best card for last, adds NEW! tags and shows rainbow borders on rare pulls.
- **Binder** showing your collection, with unowned cards as `?` slots, plus Sell and Sell Duplicates buttons.
- **3 upgrades**: Better Prices (sell bonus), Lucky Hands (better odds) and Hire Cashier (idle coins).
- **Saving** with DataStore, plus a coins and collection leaderboard.

## Setup (first time using Roblox Studio)

### 1. Install Studio and make a place
1. Download **Roblox Studio** from https://create.roblox.com and log in.
2. Click **New** and pick the **Baseplate** template.

### 2. Turn on the Explorer
At the top, open the **View** tab and click **Explorer** and **Properties**.
The Explorer panel on the right shows everything in your game.

### 3. Add the 3 scripts
Each file in `src/` goes in the place in the Explorer with the matching name.
To add one, hover over the parent in the Explorer, click the **+** button,
and pick the type shown below. Rename it by double-clicking, then
**delete the default code** and paste in the file's contents.

| File | Hover over | Click + and choose | Name it |
|---|---|---|---|
| `src/ReplicatedStorage/CardData.lua` | **ReplicatedStorage** | **ModuleScript** | `CardData` |
| `src/ServerScriptService/GameServer.server.lua` | **ServerScriptService** | **Script** | `GameServer` |
| `src/StarterPlayer/StarterPlayerScripts/GameClient.client.lua` | **StarterPlayer › StarterPlayerScripts** | **LocalScript** | `GameClient` |

The name and type matter. `CardData` must be spelled exactly like that, and
each script must be the right kind (ModuleScript, Script or LocalScript).

### 4. Play test
Press **Play** (or F5). The Pack Shop opens automatically, and you start with
100 coins. Press **Stop** (Shift+F5) to stop.

If something breaks, open **View › Output**. Red text there tells you what
went wrong. Copy it to me and I'll fix it.

### 5. Turn on saving
Saving only works once the game is published:
1. **File › Publish to Roblox**, then give it a name.
2. **Home › Game Settings › Security**, then turn on **Enable Studio Access to API Services**, and click Save.

Before you do this you'll see a yellow warning in Output saying the game is
playing without saving. That's expected.

## Changing things

Everything you'd want to tweak is in `CardData`:
- **Add a card**: add a line to `CardData.Cards` with a unique `id`.
- **Pack prices and odds**: edit `CardData.Packs`.
- **Card values**: change `value` in `CardData.Rarities`.
- **Upgrade costs**: edit `CardData.Upgrades`.

Don't rename existing card `id`s after people have played, or the cards
they already own will vanish from their binders.

## Ideas for next updates

1. **The shop world**: a 3D card shop with shelves, and NPC customers who buy your cards.
2. **Trading** between players.
3. **Grading**: send a card in for a 1–10 grade, where a 10 multiplies its value.
4. **Robux items**: a Lucky Pack game pass, 2x coins, and exclusive packs.
5. **Real card art**: upload images to replace the emoji.
6. **Sounds** for pack rips and rare pulls.
