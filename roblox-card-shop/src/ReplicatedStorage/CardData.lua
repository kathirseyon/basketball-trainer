-- CardData (ModuleScript in ReplicatedStorage)
-- All card, pack, and upgrade definitions live here so the server and client
-- agree on the same numbers. Tweak values here to rebalance the game.

local CardData = {}

-- Ordered from most common to rarest. `lucky` rarities get boosted by the
-- Lucky Hands upgrade.
CardData.Rarities = {
	{ id = "Common",   value = 5,    color = Color3.fromRGB(170, 170, 170), lucky = false },
	{ id = "Uncommon", value = 15,   color = Color3.fromRGB(90, 200, 110),  lucky = false },
	{ id = "Rare",     value = 60,   color = Color3.fromRGB(70, 140, 255),  lucky = true },
	{ id = "Holo",     value = 300,  color = Color3.fromRGB(190, 90, 255),  lucky = true },
	{ id = "Secret",   value = 2000, color = Color3.fromRGB(255, 200, 40),  lucky = true },
}

CardData.RarityById = {}
for index, rarity in ipairs(CardData.Rarities) do
	rarity.order = index
	CardData.RarityById[rarity.id] = rarity
end

-- Shiny pulls are a rare variant of any card, worth much more.
CardData.SHINY_CHANCE = 0.01
CardData.SHINY_MULTIPLIER = 5
CardData.CARDS_PER_PACK = 5

-- Original creatures only: no real Pokemon names or art.
CardData.Cards = {
	-- Common
	{ id = "sprouty",      name = "Sprouty",          icon = "🌱", rarity = "Common" },
	{ id = "puddlefin",    name = "Puddlefin",        icon = "🐟", rarity = "Common" },
	{ id = "emberpup",     name = "Emberpup",         icon = "🐕", rarity = "Common" },
	{ id = "pebblit",      name = "Pebblit",          icon = "🪨", rarity = "Common" },
	{ id = "zapling",      name = "Zapling",          icon = "⚡", rarity = "Common" },
	{ id = "fluffmoth",    name = "Fluffmoth",        icon = "🦋", rarity = "Common" },
	{ id = "snailbert",    name = "Snailbert",        icon = "🐌", rarity = "Common" },
	{ id = "toastle",      name = "Toastle",          icon = "🍞", rarity = "Common" },
	{ id = "mudbub",       name = "Mudbub",           icon = "🐸", rarity = "Common" },
	{ id = "leafkit",      name = "Leafkit",          icon = "🍃", rarity = "Common" },
	{ id = "dripdrop",     name = "Dripdrop",         icon = "💧", rarity = "Common" },
	{ id = "cinderat",     name = "Cinderat",         icon = "🐀", rarity = "Common" },
	{ id = "gumbloon",     name = "Gumbloon",         icon = "🎈", rarity = "Common" },
	{ id = "sockrates",    name = "Sockrates",        icon = "🧦", rarity = "Common" },
	{ id = "noodlenewt",   name = "Noodlenewt",       icon = "🍜", rarity = "Common" },
	-- Uncommon
	{ id = "thornclaw",    name = "Thornclaw",        icon = "🦔", rarity = "Uncommon" },
	{ id = "tidecrab",     name = "Tidecrab",         icon = "🦀", rarity = "Uncommon" },
	{ id = "voltfox",      name = "Voltfox",          icon = "🦊", rarity = "Uncommon" },
	{ id = "rockjaw",      name = "Rockjaw",          icon = "🐊", rarity = "Uncommon" },
	{ id = "frostbun",     name = "Frostbun",         icon = "🐰", rarity = "Uncommon" },
	{ id = "gloomowl",     name = "Gloomowl",         icon = "🦉", rarity = "Uncommon" },
	{ id = "bricktopus",   name = "Bricktopus",       icon = "🐙", rarity = "Uncommon" },
	{ id = "jellojolt",    name = "Jellojolt",        icon = "🍮", rarity = "Uncommon" },
	{ id = "wafflewyrm",   name = "Waffle Wyrm",      icon = "🧇", rarity = "Uncommon" },
	{ id = "cactopus",     name = "Cactopus",         icon = "🌵", rarity = "Uncommon" },
	{ id = "beetlebass",   name = "Beetlebass",       icon = "🐞", rarity = "Uncommon" },
	-- Rare
	{ id = "magmaw",       name = "Magmaw",           icon = "🌋", rarity = "Rare" },
	{ id = "stormtail",    name = "Stormtail",        icon = "🌪️", rarity = "Rare" },
	{ id = "crystalisk",   name = "Crystalisk",       icon = "💎", rarity = "Rare" },
	{ id = "shadowpaw",    name = "Shadowpaw",        icon = "🌑", rarity = "Rare" },
	{ id = "blizzbeak",    name = "Blizzbeak",        icon = "🐧", rarity = "Rare" },
	{ id = "thundertoad",  name = "Thundertoad",      icon = "⛈️", rarity = "Rare" },
	{ id = "sirpickleton", name = "Sir Pickleton",    icon = "🥒", rarity = "Rare" },
	-- Holo
	{ id = "solarion",     name = "Solarion",         icon = "☀️", rarity = "Holo" },
	{ id = "abyssqueen",   name = "Abyss Queen",      icon = "🦑", rarity = "Holo" },
	{ id = "galeking",     name = "Gale King",        icon = "🦅", rarity = "Holo" },
	{ id = "infernox",     name = "Infernox",         icon = "🐉", rarity = "Holo" },
	-- Secret
	{ id = "cosmeow",      name = "Cosmeow",          icon = "🌌", rarity = "Secret" },
	{ id = "goldfather",   name = "Goldfather Goose", icon = "🦢", rarity = "Secret" },
	{ id = "toastington",  name = "Lord Toastington", icon = "👑", rarity = "Secret" },
}

CardData.CardById = {}
CardData.CardsByRarity = {}
for _, card in ipairs(CardData.Cards) do
	CardData.CardById[card.id] = card
	CardData.CardsByRarity[card.rarity] = CardData.CardsByRarity[card.rarity] or {}
	table.insert(CardData.CardsByRarity[card.rarity], card)
end

-- Weights are relative chances per card slot (they don't need to add to 100).
CardData.Packs = {
	{
		id = "basic", name = "Basic Pack", price = 60, color = Color3.fromRGB(80, 160, 255),
		weights = { Common = 70, Uncommon = 24, Rare = 5, Holo = 0.9, Secret = 0.1 },
	},
	{
		id = "great", name = "Great Pack", price = 150, color = Color3.fromRGB(255, 90, 90),
		weights = { Common = 45, Uncommon = 35, Rare = 15, Holo = 4.5, Secret = 0.5 },
	},
	{
		id = "ultra", name = "Ultra Pack", price = 450, color = Color3.fromRGB(255, 190, 40),
		weights = { Common = 10, Uncommon = 35, Rare = 35, Holo = 17, Secret = 3 },
	},
}

CardData.PackById = {}
for _, pack in ipairs(CardData.Packs) do
	CardData.PackById[pack.id] = pack
end

CardData.Upgrades = {
	{
		id = "sell", name = "Better Prices", maxLevel = 20, baseCost = 100, costGrowth = 1.6,
		describe = function(level) return ("Sell cards for +%d%% coins"):format(level * 10) end,
	},
	{
		id = "luck", name = "Lucky Hands", maxLevel = 10, baseCost = 200, costGrowth = 1.8,
		describe = function(level) return ("+%d%% chance at Rare or better"):format(level * 10) end,
	},
	{
		id = "cashier", name = "Hire Cashier", maxLevel = 25, baseCost = 150, costGrowth = 1.5,
		describe = function(level) return ("Earn %d coins/sec, even while idle"):format(level * 2) end,
	},
}

CardData.UpgradeById = {}
for _, upgrade in ipairs(CardData.Upgrades) do
	CardData.UpgradeById[upgrade.id] = upgrade
end

function CardData.GetUpgradeCost(upgradeId, currentLevel)
	local upgrade = CardData.UpgradeById[upgradeId]
	return math.floor(upgrade.baseCost * upgrade.costGrowth ^ currentLevel)
end

-- Inventory keys are "cardId" or "cardId:shiny".
function CardData.MakeKey(cardId, isShiny)
	return isShiny and (cardId .. ":shiny") or cardId
end

function CardData.ParseKey(key)
	local cardId, suffix = string.match(key, "^([^:]+):?(.*)$")
	return CardData.CardById[cardId], suffix == "shiny"
end

-- Coins a card sells for, before the Better Prices bonus.
function CardData.GetBaseValue(key)
	local card, isShiny = CardData.ParseKey(key)
	if not card then
		return 0
	end
	local value = CardData.RarityById[card.rarity].value
	return isShiny and value * CardData.SHINY_MULTIPLIER or value
end

function CardData.GetSellPrice(key, sellLevel)
	return math.floor(CardData.GetBaseValue(key) * (1 + 0.1 * sellLevel))
end

return CardData
