# Card Shop Simulator (Roblox)

A pack-opening card collecting game for Roblox. Buy packs, pull creatures,
fill your binder, put cards on display in your own 3D card shop, and let
customers buy them.

All creatures are original. Don't add real Pokémon names or art, because
Roblox will take the game down.

## What's in version 1

- **3 packs**: Basic, Great and Ultra. Each has 5 cards with different rarity odds.
- **40 cards** in 5 rarities: Common, Uncommon, Rare, Holo and Secret. Any card has a 1% chance to be a **Shiny** worth 5x.
- **Pack reveal animation** that saves the best card for last, adds NEW! tags and shows rainbow borders on rare pulls.
- **Binder** showing your collection, with undiscovered cards as `?` slots, plus Sell, Display and Sell Duplicates buttons. Cards you found before still count toward your collection after you sell them.
- **Your own card shop**: every player gets a shop on one of 6 plots, with their name on the sign.
- **Display cases**: put a card on display, and NPC customers walk in, look around and buy it for **2× the sell price**. If you have a spare copy of that card, it restocks automatically.
- **5 upgrades**: Better Prices (sell bonus), Lucky Hands (better odds), Hire Cashier (idle coins), Display Cases (up to 8) and Advertising (more customers).
- **Saving** with DataStore, plus a coins and collection leaderboard.

## Setup (first time using Roblox Studio)

### 1. Install Studio and make a place
1. Download **Roblox Studio** from https://create.roblox.com and log in.
2. Click **New** and pick the **Baseplate** template.

### 2. Turn on the Explorer
At the top, open the **View** tab and click **Explorer** and **Properties**.
The Explorer panel on the right shows everything in your game.

### 3. Add the 4 scripts
Each file in `src/` goes in the place in the Explorer with the matching name.
To add one, hover over the parent in the Explorer, click the **+** button,
and pick the type shown below. Rename it by double-clicking, then
**delete the default code** and paste in the file's contents.

| File | Hover over | Click + and choose | Name it |
|---|---|---|---|
| `src/ReplicatedStorage/CardData.lua` | **ReplicatedStorage** | **ModuleScript** | `CardData` |
| `src/ServerScriptService/ShopWorld.lua` | **ServerScriptService** | **ModuleScript** | `ShopWorld` |
| `src/ServerScriptService/GameServer.server.lua` | **ServerScriptService** | **Script** | `GameServer` |
| `src/StarterPlayer/StarterPlayerScripts/GameClient.client.lua` | **StarterPlayer › StarterPlayerScripts** | **LocalScript** | `GameClient` |

The name and type matter. `CardData` and `ShopWorld` must be spelled exactly
like that, and each script must be the right kind (ModuleScript, Script or
LocalScript).

**Updating from version 1?** Paste the new code over all 3 old scripts, then
add `ShopWorld` as a new ModuleScript.

### 4. Play test
Press **Play** (or F5). You spawn in front of your own shop, the Pack Shop
menu opens, and you start with 100 coins. Press **Stop** (Shift+F5) to stop.

How to play:
1. Open a few packs.
2. Open the **📖 Binder** and press **🏪 Display** on a card. It appears on a case in your shop.
3. Customers walk in every ~10 seconds. A 💰 means they bought something, and a 😞 means your cases were empty.
4. Walk up to a case and press **E** to take a card back, or to stock an empty case.

To test with several players, go to the **Test** tab, set Clients to 2, and press **Start**.

If something breaks, open **View › Output**. Red text there tells you what
went wrong. Copy it to me and I'll fix it.

### 5. Turn on saving
Saving only works once the game is published:
1. **File › Publish to Roblox**, then give it a name.
2. **Home › Game Settings › Security**, then turn on **Enable Studio Access to API Services**, and click Save.

Before you do this you'll see a yellow warning in Output saying the game is
playing without saving. That's expected.

### 6. Limit server size
There are 6 shop plots, so set your game's **Max Players to 6** in your place
settings (Game Settings → Places). Extra players can still open packs, but
they won't get a shop.

## Changing things

Everything you'd want to tweak is in `CardData`:
- **Add a card**: add a line to `CardData.Cards` with a unique `id`.
- **Pack prices and odds**: edit `CardData.Packs`.
- **Card values**: change `value` in `CardData.Rarities`.
- **Upgrade costs**: edit `CardData.Upgrades`.
- **Shop prices and customer speed**: `SHOP_PRICE_MULTIPLIER`, `MAX_CUSTOMERS` and `GetCustomerInterval`.
- **Shop layout**: the walls, counter and case spots are near the top of `ShopWorld`.

Don't rename existing card `id`s after people have played, or the cards
they already own will vanish from their binders.

## Ideas for next updates

1. **Trading** between players, at a trading table in the middle of the map.
2. **Visiting shops**: buy cards from other players' display cases.
3. **Grading**: send a card in for a 1–10 grade, where a 10 multiplies its value.
4. **Robux items**: a Lucky Pack game pass, 2x coins, and exclusive packs.
5. **Real card art**: upload images to replace the emoji.
6. **Sounds** for pack rips and rare pulls.
