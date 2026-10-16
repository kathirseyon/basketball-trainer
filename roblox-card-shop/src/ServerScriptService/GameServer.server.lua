-- GameServer (Script in ServerScriptService)
-- Owns all player data. The client only asks; the server decides pulls,
-- coins, and upgrades so exploiters can't give themselves cards.

local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local CardData = require(ReplicatedStorage:WaitForChild("CardData"))

local DATA_VERSION_KEY = "CardShop_v1"
local STARTING_COINS = 100
local PACK_COOLDOWN = 0.75 -- seconds between pack opens
local AUTOSAVE_INTERVAL = 60

local store
do
	local ok, result = pcall(function()
		return DataStoreService:GetDataStore(DATA_VERSION_KEY)
	end)
	if ok then
		store = result
	else
		warn("[CardShop] DataStore unavailable, progress will not save: " .. tostring(result))
	end
end

-- Remotes ------------------------------------------------------------------

local remotes = Instance.new("Folder")
remotes.Name = "Remotes"
remotes.Parent = ReplicatedStorage

local function makeRemote(className, name)
	local remote = Instance.new(className)
	remote.Name = name
	remote.Parent = remotes
	return remote
end

local OpenPack = makeRemote("RemoteFunction", "OpenPack")
local SellCard = makeRemote("RemoteFunction", "SellCard")
local SellDuplicates = makeRemote("RemoteFunction", "SellDuplicates")
local BuyUpgrade = makeRemote("RemoteFunction", "BuyUpgrade")
local GetState = makeRemote("RemoteFunction", "GetState")
local StateChanged = makeRemote("RemoteEvent", "StateChanged")

-- Player data --------------------------------------------------------------

local sessionData = {} -- [player] = data table
local canSave = {} -- [player] = true only if their data loaded cleanly
local lastPackTime = {}
local rng = Random.new()

local function newData()
	return {
		coins = STARTING_COINS,
		cards = {}, -- [key] = count
		upgrades = { sell = 0, luck = 0, cashier = 0 },
		packsOpened = 0,
	}
end

-- Fill in fields added in later updates so old saves keep working.
local function reconcile(data)
	local template = newData()
	for field, default in pairs(template) do
		if data[field] == nil then
			data[field] = default
		end
	end
	for upgradeId, default in pairs(template.upgrades) do
		if data.upgrades[upgradeId] == nil then
			data.upgrades[upgradeId] = default
		end
	end
	return data
end

local function countUnique(data)
	local seen = {}
	local total = 0
	for key, count in pairs(data.cards) do
		local card = CardData.ParseKey(key)
		if card and count > 0 and not seen[card.id] then
			seen[card.id] = true
			total += 1
		end
	end
	return total
end

local function updateLeaderstats(player)
	local data = sessionData[player]
	local stats = player:FindFirstChild("leaderstats")
	if not data or not stats then
		return
	end
	stats.Coins.Value = data.coins
	stats.Collection.Value = countUnique(data)
end

local function pushState(player)
	local data = sessionData[player]
	if not data then
		return
	end
	updateLeaderstats(player)
	StateChanged:FireClient(player, data)
end

local function loadData(player)
	if not store then
		return newData(), false
	end
	for attempt = 1, 3 do
		local ok, result = pcall(function()
			return store:GetAsync("player_" .. player.UserId)
		end)
		if ok then
			return reconcile(result or newData()), true
		end
		warn(("[CardShop] Load attempt %d failed for %s: %s"):format(attempt, player.Name, tostring(result)))
		task.wait(2)
	end
	-- Don't save over their real data if we couldn't read it.
	return newData(), false
end

local function saveData(player)
	local data = sessionData[player]
	if not store or not data or not canSave[player] then
		return
	end
	local ok, err = pcall(function()
		store:UpdateAsync("player_" .. player.UserId, function()
			return data
		end)
	end)
	if not ok then
		warn("[CardShop] Save failed for " .. player.Name .. ": " .. tostring(err))
	end
end

local function onPlayerAdded(player)
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Parent = stats
	local collection = Instance.new("IntValue")
	collection.Name = "Collection"
	collection.Parent = stats
	stats.Parent = player

	local data, loadedOk = loadData(player)
	if not player.Parent then
		return -- left while loading
	end
	sessionData[player] = data
	canSave[player] = loadedOk
	if not loadedOk then
		warn("[CardShop] Playing without saving for " .. player.Name)
	end
	pushState(player)
end

local function onPlayerRemoving(player)
	saveData(player)
	sessionData[player] = nil
	canSave[player] = nil
	lastPackTime[player] = nil
end

Players.PlayerAdded:Connect(onPlayerAdded)
Players.PlayerRemoving:Connect(onPlayerRemoving)
for _, player in ipairs(Players:GetPlayers()) do
	task.spawn(onPlayerAdded, player)
end

game:BindToClose(function()
	for _, player in ipairs(Players:GetPlayers()) do
		task.spawn(saveData, player)
	end
	task.wait(RunService:IsStudio() and 1 or 5)
end)

task.spawn(function()
	while true do
		task.wait(AUTOSAVE_INTERVAL)
		for _, player in ipairs(Players:GetPlayers()) do
			task.spawn(saveData, player)
		end
	end
end)

-- Game logic ---------------------------------------------------------------

local function rollRarity(pack, luckLevel)
	local weights = {}
	local total = 0
	for _, rarity in ipairs(CardData.Rarities) do
		local weight = pack.weights[rarity.id] or 0
		if rarity.lucky then
			weight *= 1 + 0.1 * luckLevel
		end
		weights[rarity.id] = weight
		total += weight
	end

	local roll = rng:NextNumber() * total
	for _, rarity in ipairs(CardData.Rarities) do
		roll -= weights[rarity.id]
		if roll <= 0 then
			return rarity.id
		end
	end
	return CardData.Rarities[1].id
end

local function rollCard(pack, luckLevel)
	local pool = CardData.CardsByRarity[rollRarity(pack, luckLevel)]
	local card = pool[rng:NextInteger(1, #pool)]
	local isShiny = rng:NextNumber() < CardData.SHINY_CHANCE
	return CardData.MakeKey(card.id, isShiny)
end

OpenPack.OnServerInvoke = function(player, packId)
	local data = sessionData[player]
	if not data then
		return { ok = false, err = "Still loading your data..." }
	end
	local pack = type(packId) == "string" and CardData.PackById[packId]
	if not pack then
		return { ok = false, err = "Unknown pack" }
	end
	local now = os.clock()
	if lastPackTime[player] and now - lastPackTime[player] < PACK_COOLDOWN then
		return { ok = false, err = "Slow down!" }
	end
	if data.coins < pack.price then
		return { ok = false, err = "Not enough coins" }
	end
	lastPackTime[player] = now

	data.coins -= pack.price
	data.packsOpened += 1
	local pulls = {}
	for _ = 1, CardData.CARDS_PER_PACK do
		local key = rollCard(pack, data.upgrades.luck)
		local isNew = (data.cards[key] or 0) == 0
		data.cards[key] = (data.cards[key] or 0) + 1
		table.insert(pulls, { key = key, isNew = isNew })
	end

	pushState(player)
	return { ok = true, pulls = pulls }
end

SellCard.OnServerInvoke = function(player, key)
	local data = sessionData[player]
	if not data or type(key) ~= "string" then
		return { ok = false, err = "Can't sell that" }
	end
	local count = data.cards[key] or 0
	if count <= 0 then
		return { ok = false, err = "You don't own that card" }
	end
	local price = CardData.GetSellPrice(key, data.upgrades.sell)
	data.cards[key] = count > 1 and count - 1 or nil
	data.coins += price
	pushState(player)
	return { ok = true, earned = price }
end

-- Sells every copy beyond the first, so the binder stays complete.
SellDuplicates.OnServerInvoke = function(player)
	local data = sessionData[player]
	if not data then
		return { ok = false, err = "Still loading your data..." }
	end
	local earned = 0
	for key, count in pairs(data.cards) do
		if count > 1 then
			earned += CardData.GetSellPrice(key, data.upgrades.sell) * (count - 1)
			data.cards[key] = 1
		end
	end
	if earned == 0 then
		return { ok = false, err = "No duplicates to sell" }
	end
	data.coins += earned
	pushState(player)
	return { ok = true, earned = earned }
end

BuyUpgrade.OnServerInvoke = function(player, upgradeId)
	local data = sessionData[player]
	local upgrade = type(upgradeId) == "string" and CardData.UpgradeById[upgradeId]
	if not data or not upgrade then
		return { ok = false, err = "Unknown upgrade" }
	end
	local level = data.upgrades[upgradeId]
	if level >= upgrade.maxLevel then
		return { ok = false, err = "Already maxed" }
	end
	local cost = CardData.GetUpgradeCost(upgradeId, level)
	if data.coins < cost then
		return { ok = false, err = "Not enough coins" }
	end
	data.coins -= cost
	data.upgrades[upgradeId] = level + 1
	pushState(player)
	return { ok = true }
end

GetState.OnServerInvoke = function(player)
	return sessionData[player]
end

-- Cashier passive income. Only coins change, so update leaderstats
-- (which replicate on their own) instead of re-sending the whole binder.
task.spawn(function()
	while true do
		task.wait(1)
		for player, data in pairs(sessionData) do
			local income = data.upgrades.cashier * 2
			if income > 0 then
				data.coins += income
				updateLeaderstats(player)
			end
		end
	end
end)
