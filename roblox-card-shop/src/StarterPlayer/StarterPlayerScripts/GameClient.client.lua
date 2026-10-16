-- GameClient (LocalScript in StarterPlayer > StarterPlayerScripts)
-- Builds the whole UI in code: coin bar, side menu, pack shop, binder,
-- upgrades, and the pack-opening reveal.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")

local CardData = require(ReplicatedStorage:WaitForChild("CardData"))
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local player = Players.LocalPlayer

local WHITE = Color3.new(1, 1, 1)
local DARK = Color3.fromRGB(35, 35, 45)
local PANEL = Color3.fromRGB(30, 32, 48)
local GREEN = Color3.fromRGB(60, 190, 90)
local RED = Color3.fromRGB(220, 70, 70)
local GREY = Color3.fromRGB(110, 110, 120)
local CREAM = Color3.fromRGB(248, 243, 228)
local FONT = Enum.Font.FredokaOne

local state = nil -- latest data from the server
local busy = false
local lastPackId = nil

-- Helpers ------------------------------------------------------------------

local function create(className, props, children)
	local inst = Instance.new(className)
	for key, value in pairs(props or {}) do
		if key ~= "Parent" then
			inst[key] = value
		end
	end
	for _, child in ipairs(children or {}) do
		child.Parent = inst
	end
	if props and props.Parent then
		inst.Parent = props.Parent
	end
	return inst
end

local function round(parent, radius)
	return create("UICorner", { CornerRadius = UDim.new(0, radius or 10), Parent = parent })
end

local function label(props)
	props.BackgroundTransparency = props.BackgroundTransparency or 1
	props.Font = FONT
	props.TextColor3 = props.TextColor3 or WHITE
	props.TextScaled = true
	return create("TextLabel", props)
end

local function button(props)
	props.Font = FONT
	props.TextColor3 = props.TextColor3 or WHITE
	props.TextScaled = true
	local btn = create("TextButton", props)
	round(btn, 8)
	create("UIPadding", {
		PaddingTop = UDim.new(0.18, 0), PaddingBottom = UDim.new(0.18, 0),
		PaddingLeft = UDim.new(0, 6), PaddingRight = UDim.new(0, 6), Parent = btn,
	})
	return btn
end

local function formatNumber(n)
	local formatted = tostring(math.floor(n)):reverse():gsub("(%d%d%d)", "%1,"):reverse()
	return (formatted:gsub("^,", ""))
end

local function getCoins()
	local stats = player:FindFirstChild("leaderstats")
	local coins = stats and stats:FindFirstChild("Coins")
	return coins and coins.Value or 0
end

local function sellLevel()
	return state and state.upgrades.sell or 0
end

-- Holo, Secret and Shiny cards get a spinning rainbow border.
local RAINBOW = ColorSequence.new({
	ColorSequenceKeypoint.new(0, Color3.fromRGB(255, 80, 80)),
	ColorSequenceKeypoint.new(0.25, Color3.fromRGB(255, 220, 60)),
	ColorSequenceKeypoint.new(0.5, Color3.fromRGB(80, 230, 120)),
	ColorSequenceKeypoint.new(0.75, Color3.fromRGB(80, 160, 255)),
	ColorSequenceKeypoint.new(1, Color3.fromRGB(220, 90, 255)),
})
local shimmers = setmetatable({}, { __mode = "k" })
RunService.RenderStepped:Connect(function()
	local rotation = (os.clock() * 180) % 360
	for gradient in pairs(shimmers) do
		gradient.Rotation = rotation
	end
end)

-- Screen -------------------------------------------------------------------

local gui = create("ScreenGui", {
	Name = "CardShopUI", ResetOnSpawn = false,
	ZIndexBehavior = Enum.ZIndexBehavior.Sibling,
	Parent = player:WaitForChild("PlayerGui"),
})

local toastLabel = label({
	AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.new(0.5, 0, 0, 64),
	Size = UDim2.new(0.5, 0, 0, 36), Text = "", Visible = false, ZIndex = 50,
	TextStrokeTransparency = 0.3, Parent = gui,
})
local toastToken = 0
local function toast(text, color)
	toastToken += 1
	local token = toastToken
	toastLabel.Text = text
	toastLabel.TextColor3 = color or WHITE
	toastLabel.Visible = true
	task.delay(2, function()
		if toastToken == token then
			toastLabel.Visible = false
		end
	end)
end

-- Top bar: coins + collection
local topBar = create("Frame", {
	AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.new(0.5, 0, 0, 8),
	Size = UDim2.new(0.4, 0, 0, 46), BackgroundColor3 = PANEL, BackgroundTransparency = 0.15,
	Parent = gui,
})
round(topBar, 12)
create("UISizeConstraint", { MinSize = Vector2.new(260, 46), MaxSize = Vector2.new(480, 46), Parent = topBar })
local coinsLabel = label({
	Text = "🪙 0", Position = UDim2.fromScale(0.04, 0.12), Size = UDim2.fromScale(0.5, 0.76),
	TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = Color3.fromRGB(255, 215, 80), Parent = topBar,
})
local collectionLabel = label({
	Text = "📖 0/" .. #CardData.Cards, Position = UDim2.fromScale(0.54, 0.12), Size = UDim2.fromScale(0.42, 0.76),
	TextXAlignment = Enum.TextXAlignment.Right, Parent = topBar,
})

-- Panels -------------------------------------------------------------------

local panels = {}
local panelRefreshers = {}

local function closePanels()
	for _, panel in pairs(panels) do
		panel.Visible = false
	end
end

local function makePanel(name, title)
	local frame = create("Frame", {
		Name = name, AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.52),
		Size = UDim2.fromScale(0.8, 0.72), BackgroundColor3 = PANEL, Visible = false, Parent = gui,
	})
	round(frame, 16)
	create("UIStroke", { Color = Color3.fromRGB(90, 95, 140), Thickness = 3, Parent = frame })
	create("UISizeConstraint", { MaxSize = Vector2.new(860, 580), Parent = frame })
	label({
		Text = title, Position = UDim2.fromOffset(16, 8), Size = UDim2.new(1, -80, 0, 40),
		TextXAlignment = Enum.TextXAlignment.Left, Parent = frame,
	})
	local close = button({
		Text = "X", Position = UDim2.new(1, -50, 0, 8), Size = UDim2.fromOffset(40, 40),
		BackgroundColor3 = RED, Parent = frame,
	})
	close.Activated:Connect(function()
		frame.Visible = false
	end)
	local content = create("Frame", {
		BackgroundTransparency = 1, Position = UDim2.fromOffset(16, 58),
		Size = UDim2.new(1, -32, 1, -74), Parent = frame,
	})
	panels[name] = frame
	return content
end

local function togglePanel(name)
	local opening = not panels[name].Visible
	closePanels()
	panels[name].Visible = opening
	if opening and panelRefreshers[name] then
		panelRefreshers[name]()
	end
end

-- Card visual --------------------------------------------------------------

local function makeCard(key, parent)
	local card, isShiny = CardData.ParseKey(key)
	local rarity = CardData.RarityById[card.rarity]
	local frame = create("Frame", { BackgroundColor3 = CREAM, Size = UDim2.fromScale(1, 1), Parent = parent })
	round(frame, 10)
	local stroke = create("UIStroke", { Color = rarity.color, Thickness = 4, Parent = frame })
	if rarity.order >= 4 or isShiny then
		stroke.Color = WHITE
		shimmers[create("UIGradient", { Color = RAINBOW, Parent = stroke })] = true
	end

	local art = create("Frame", {
		BackgroundColor3 = rarity.color, Position = UDim2.fromScale(0.08, 0.06),
		Size = UDim2.fromScale(0.84, 0.5), Parent = frame,
	})
	round(art, 8)
	if isShiny then
		create("UIGradient", { Color = RAINBOW, Rotation = 45, Parent = art })
	end
	label({ Text = card.icon, Position = UDim2.fromScale(0.1, 0.1), Size = UDim2.fromScale(0.8, 0.8), Parent = art })

	label({
		Text = card.name, TextColor3 = DARK, Position = UDim2.fromScale(0.05, 0.58),
		Size = UDim2.fromScale(0.9, 0.13), Parent = frame,
	})
	label({
		Text = (isShiny and "✨ Shiny " or "") .. rarity.id,
		TextColor3 = rarity.color:Lerp(Color3.new(0, 0, 0), 0.35),
		Position = UDim2.fromScale(0.05, 0.72), Size = UDim2.fromScale(0.9, 0.1), Parent = frame,
	})
	label({
		Text = "🪙 " .. formatNumber(CardData.GetSellPrice(key, sellLevel())), TextColor3 = DARK,
		Position = UDim2.fromScale(0.05, 0.84), Size = UDim2.fromScale(0.9, 0.1), Parent = frame,
	})
	return frame
end

-- Pack reveal overlay ------------------------------------------------------

local overlay = create("Frame", {
	Size = UDim2.fromScale(1, 1), BackgroundColor3 = Color3.new(0, 0, 0),
	BackgroundTransparency = 0.2, Visible = false, ZIndex = 10, Parent = gui,
})
local revealTitle = label({
	AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.fromScale(0.5, 0.08),
	Size = UDim2.fromScale(0.6, 0.08), Text = "", Parent = overlay,
})
local cardRow = create("Frame", {
	AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.47),
	Size = UDim2.fromScale(0.95, 0.5), BackgroundTransparency = 1, Parent = overlay,
})
create("UIListLayout", {
	FillDirection = Enum.FillDirection.Horizontal, HorizontalAlignment = Enum.HorizontalAlignment.Center,
	VerticalAlignment = Enum.VerticalAlignment.Center, Padding = UDim.new(0.015, 0),
	SortOrder = Enum.SortOrder.LayoutOrder, Parent = cardRow,
})
local revealTotal = label({
	AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.fromScale(0.5, 0.76),
	Size = UDim2.fromScale(0.6, 0.06), Text = "", TextColor3 = Color3.fromRGB(255, 215, 80), Parent = overlay,
})
local againButton = button({
	AnchorPoint = Vector2.new(1, 0), Position = UDim2.fromScale(0.49, 0.85),
	Size = UDim2.fromScale(0.2, 0.08), Text = "Open Another", BackgroundColor3 = GREEN, Parent = overlay,
})
local doneButton = button({
	Position = UDim2.fromScale(0.51, 0.85), Size = UDim2.fromScale(0.2, 0.08),
	Text = "Done", BackgroundColor3 = GREY, Parent = overlay,
})

local function rarityOrder(key)
	local card = CardData.ParseKey(key)
	return CardData.RarityById[card.rarity].order
end

local function showReveal(pack, pulls)
	for _, child in ipairs(cardRow:GetChildren()) do
		if child:IsA("GuiObject") then
			child:Destroy()
		end
	end
	overlay.Visible = true
	againButton.Visible = false
	doneButton.Visible = false
	revealTitle.Text = pack.name
	revealTotal.Text = ""

	-- Save the best card for last.
	table.sort(pulls, function(a, b)
		return rarityOrder(a.key) < rarityOrder(b.key)
	end)

	local total = 0
	for index, pull in ipairs(pulls) do
		local slot = create("Frame", {
			BackgroundTransparency = 1, Size = UDim2.fromScale(0.17, 1), LayoutOrder = index, Parent = cardRow,
		})
		create("UIAspectRatioConstraint", { AspectRatio = 0.68, Parent = slot })

		local _, isShiny = CardData.ParseKey(pull.key)
		local big = rarityOrder(pull.key) >= 3 or isShiny
		task.wait(big and 0.7 or 0.3)

		local cardFrame = makeCard(pull.key, slot)
		cardFrame.AnchorPoint = Vector2.new(0.5, 0.5)
		cardFrame.Position = UDim2.fromScale(0.5, 0.5)
		cardFrame.Size = UDim2.fromScale(0.1, 0.1)
		TweenService:Create(cardFrame, TweenInfo.new(0.35, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {
			Size = UDim2.fromScale(1, 1),
		}):Play()

		if pull.isNew then
			local tag = label({
				Text = "NEW!", BackgroundTransparency = 0, BackgroundColor3 = RED,
				AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.85, 0.03),
				Size = UDim2.fromScale(0.5, 0.11), Rotation = 12, ZIndex = 5, Parent = cardFrame,
			})
			round(tag, 6)
		end
		if big then
			local card = CardData.ParseKey(pull.key)
			toast(("WOW! %s%s!"):format(isShiny and "Shiny " or "", card.name), Color3.fromRGB(255, 215, 80))
		end

		total += CardData.GetSellPrice(pull.key, sellLevel())
		revealTotal.Text = "Pack value: 🪙 " .. formatNumber(total)
	end

	againButton.Text = ("Open Another (🪙%s)"):format(formatNumber(pack.price))
	againButton.Visible = true
	doneButton.Visible = true
end

local function openPack(packId)
	if busy then
		return
	end
	local pack = CardData.PackById[packId]
	if getCoins() < pack.price then
		toast("Not enough coins!", RED)
		return
	end
	busy = true
	local result = remotes.OpenPack:InvokeServer(packId)
	if result and result.ok then
		lastPackId = packId
		closePanels()
		showReveal(pack, result.pulls)
	else
		toast(result and result.err or "Something went wrong", RED)
	end
	busy = false
end

againButton.Activated:Connect(function()
	if lastPackId then
		openPack(lastPackId)
	end
end)
doneButton.Activated:Connect(function()
	overlay.Visible = false
end)

-- Packs panel --------------------------------------------------------------

local packsContent = makePanel("Packs", "📦 Pack Shop")
create("UIListLayout", {
	FillDirection = Enum.FillDirection.Horizontal, HorizontalAlignment = Enum.HorizontalAlignment.Center,
	Padding = UDim.new(0.03, 0), SortOrder = Enum.SortOrder.LayoutOrder, Parent = packsContent,
})

local packButtons = {}
for index, pack in ipairs(CardData.Packs) do
	local frame = create("Frame", {
		BackgroundColor3 = pack.color, Size = UDim2.fromScale(0.3, 1), LayoutOrder = index, Parent = packsContent,
	})
	round(frame, 14)
	label({ Text = pack.name, Position = UDim2.fromScale(0.05, 0.03), Size = UDim2.fromScale(0.9, 0.11), Parent = frame })
	label({ Text = "📦", Position = UDim2.fromScale(0.2, 0.15), Size = UDim2.fromScale(0.6, 0.25), Parent = frame })

	local totalWeight = 0
	for _, weight in pairs(pack.weights) do
		totalWeight += weight
	end
	local lines = {}
	for _, rarity in ipairs(CardData.Rarities) do
		local percent = (pack.weights[rarity.id] or 0) / totalWeight * 100
		table.insert(lines, ('<font color="#%s">%s</font> %.1f%%'):format(rarity.color:ToHex(), rarity.id, percent))
	end
	local odds = label({
		Text = table.concat(lines, "\n"), RichText = true, BackgroundTransparency = 0.3,
		BackgroundColor3 = DARK, Position = UDim2.fromScale(0.08, 0.42), Size = UDim2.fromScale(0.84, 0.36),
		Parent = frame,
	})
	round(odds, 8)
	create("UIPadding", { PaddingTop = UDim.new(0, 6), PaddingBottom = UDim.new(0, 6), Parent = odds })

	local buy = button({
		Text = "Open  🪙" .. formatNumber(pack.price), BackgroundColor3 = GREEN,
		Position = UDim2.fromScale(0.08, 0.82), Size = UDim2.fromScale(0.84, 0.14), Parent = frame,
	})
	buy.Activated:Connect(function()
		openPack(pack.id)
	end)
	packButtons[pack.id] = buy
end

local function refreshPacks()
	local coins = getCoins()
	for _, pack in ipairs(CardData.Packs) do
		packButtons[pack.id].BackgroundColor3 = coins >= pack.price and GREEN or GREY
	end
end
panelRefreshers.Packs = refreshPacks

-- Binder panel -------------------------------------------------------------

local binderContent = makePanel("Binder", "📖 My Binder")
local sellDupesButton = button({
	Text = "Sell Duplicates", BackgroundColor3 = GREEN, Size = UDim2.new(0, 280, 0, 40), Parent = binderContent,
})
local binderScroll = create("ScrollingFrame", {
	Position = UDim2.fromOffset(0, 50), Size = UDim2.new(1, 0, 1, -50), BackgroundTransparency = 1,
	CanvasSize = UDim2.new(), AutomaticCanvasSize = Enum.AutomaticSize.Y, ScrollBarThickness = 8,
	Parent = binderContent,
})
create("UIPadding", {
	PaddingTop = UDim.new(0, 6), PaddingLeft = UDim.new(0, 6),
	PaddingRight = UDim.new(0, 14), PaddingBottom = UDim.new(0, 6), Parent = binderScroll,
})
create("UIGridLayout", {
	CellSize = UDim2.fromOffset(110, 196), CellPadding = UDim2.fromOffset(12, 12),
	SortOrder = Enum.SortOrder.LayoutOrder, Parent = binderScroll,
})

local function sellCard(key)
	local result = remotes.SellCard:InvokeServer(key)
	if result and result.ok then
		toast("+🪙 " .. formatNumber(result.earned), GREEN)
	else
		toast(result and result.err or "Couldn't sell", RED)
	end
end

local function makeSellButton(key, count, cell)
	local price = CardData.GetSellPrice(key, sellLevel())
	local text = "Sell 🪙" .. formatNumber(price)
	local sellButton = button({
		Text = text, BackgroundColor3 = RED, AnchorPoint = Vector2.new(0, 1),
		Position = UDim2.fromScale(0, 1), Size = UDim2.new(1, 0, 0, 30), Parent = cell,
	})
	-- Ask twice before selling your last copy of something Rare or better.
	local needsConfirm = count == 1 and rarityOrder(key) >= 3
	local armed = false
	sellButton.Activated:Connect(function()
		if needsConfirm and not armed then
			armed = true
			sellButton.Text = "Sure? Last one!"
			task.delay(2, function()
				armed = false
				sellButton.Text = text
			end)
			return
		end
		sellCard(key)
	end)
end

local function refreshBinder()
	if not state then
		return
	end
	for _, child in ipairs(binderScroll:GetChildren()) do
		if child:IsA("GuiObject") then
			child:Destroy()
		end
	end

	local order = 0
	local dupeValue = 0
	for _, card in ipairs(CardData.Cards) do
		for _, isShiny in ipairs({ false, true }) do
			local key = CardData.MakeKey(card.id, isShiny)
			local count = state.cards[key] or 0
			if count > 1 then
				dupeValue += CardData.GetSellPrice(key, sellLevel()) * (count - 1)
			end
			-- Always show a slot for the normal card; shinies only once owned.
			if count > 0 or not isShiny then
				order += 1
				local cell = create("Frame", { BackgroundTransparency = 1, LayoutOrder = order, Parent = binderScroll })
				if count > 0 then
					local cardFrame = makeCard(key, cell)
					cardFrame.Size = UDim2.new(1, 0, 1, -36)
					if count > 1 then
						local badge = label({
							Text = "x" .. count, BackgroundTransparency = 0, BackgroundColor3 = DARK,
							AnchorPoint = Vector2.new(1, 0), Position = UDim2.new(1, 4, 0, -4),
							Size = UDim2.fromOffset(38, 22), ZIndex = 5, Parent = cardFrame,
						})
						round(badge, 6)
					end
					makeSellButton(key, count, cell)
				else
					local locked = create("Frame", {
						BackgroundColor3 = Color3.fromRGB(55, 58, 80), Size = UDim2.new(1, 0, 1, -36), Parent = cell,
					})
					round(locked, 10)
					label({ Text = "?", TextColor3 = GREY, Position = UDim2.fromScale(0.2, 0.15), Size = UDim2.fromScale(0.6, 0.45), Parent = locked })
					label({
						Text = card.rarity, TextColor3 = CardData.RarityById[card.rarity].color,
						Position = UDim2.fromScale(0.05, 0.72), Size = UDim2.fromScale(0.9, 0.12), Parent = locked,
					})
				end
			end
		end
	end

	if dupeValue > 0 then
		sellDupesButton.Text = "Sell Duplicates (+🪙" .. formatNumber(dupeValue) .. ")"
		sellDupesButton.BackgroundColor3 = GREEN
	else
		sellDupesButton.Text = "No Duplicates"
		sellDupesButton.BackgroundColor3 = GREY
	end
end
panelRefreshers.Binder = refreshBinder

sellDupesButton.Activated:Connect(function()
	local result = remotes.SellDuplicates:InvokeServer()
	if result and result.ok then
		toast("+🪙 " .. formatNumber(result.earned), GREEN)
	else
		toast(result and result.err or "Couldn't sell", RED)
	end
end)

-- Upgrades panel -----------------------------------------------------------

local upgradesContent = makePanel("Upgrades", "⬆️ Shop Upgrades")
create("UIListLayout", { Padding = UDim.new(0.04, 0), SortOrder = Enum.SortOrder.LayoutOrder, Parent = upgradesContent })

local upgradeRows = {}
for index, upgrade in ipairs(CardData.Upgrades) do
	local row = create("Frame", {
		BackgroundColor3 = Color3.fromRGB(45, 48, 70), Size = UDim2.fromScale(1, 0.28), LayoutOrder = index, Parent = upgradesContent,
	})
	round(row, 12)
	local nameLabel = label({
		Position = UDim2.fromScale(0.03, 0.1), Size = UDim2.fromScale(0.62, 0.42),
		TextXAlignment = Enum.TextXAlignment.Left, Text = upgrade.name, Parent = row,
	})
	local descLabel = label({
		Position = UDim2.fromScale(0.03, 0.56), Size = UDim2.fromScale(0.62, 0.3),
		TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = Color3.fromRGB(190, 195, 220), Text = "", Parent = row,
	})
	local buy = button({
		AnchorPoint = Vector2.new(1, 0.5), Position = UDim2.fromScale(0.97, 0.5),
		Size = UDim2.fromScale(0.28, 0.6), BackgroundColor3 = GREEN, Text = "", Parent = row,
	})
	buy.Activated:Connect(function()
		local result = remotes.BuyUpgrade:InvokeServer(upgrade.id)
		if result and result.ok then
			toast(upgrade.name .. " upgraded!", GREEN)
		else
			toast(result and result.err or "Couldn't upgrade", RED)
		end
	end)
	upgradeRows[upgrade.id] = { name = nameLabel, desc = descLabel, buy = buy }
end

local function refreshUpgrades()
	if not state then
		return
	end
	local coins = getCoins()
	for _, upgrade in ipairs(CardData.Upgrades) do
		local row = upgradeRows[upgrade.id]
		local level = state.upgrades[upgrade.id]
		row.name.Text = ("%s  (Lv %d/%d)"):format(upgrade.name, level, upgrade.maxLevel)
		if level >= upgrade.maxLevel then
			row.desc.Text = upgrade.describe(level) .. " (MAX)"
			row.buy.Text = "MAXED"
			row.buy.BackgroundColor3 = GREY
		else
			local cost = CardData.GetUpgradeCost(upgrade.id, level)
			row.desc.Text = "Next: " .. upgrade.describe(level + 1)
			row.buy.Text = "🪙 " .. formatNumber(cost)
			row.buy.BackgroundColor3 = coins >= cost and GREEN or GREY
		end
	end
end
panelRefreshers.Upgrades = refreshUpgrades

-- Side menu ----------------------------------------------------------------

local menu = create("Frame", {
	AnchorPoint = Vector2.new(0, 0.5), Position = UDim2.new(0, 12, 0.5, 0),
	Size = UDim2.fromOffset(140, 190), BackgroundTransparency = 1, Parent = gui,
})
create("UIListLayout", { Padding = UDim.new(0, 10), SortOrder = Enum.SortOrder.LayoutOrder, Parent = menu })
for index, entry in ipairs({
	{ name = "Packs", text = "📦 Packs", color = Color3.fromRGB(80, 160, 255) },
	{ name = "Binder", text = "📖 Binder", color = Color3.fromRGB(190, 90, 255) },
	{ name = "Upgrades", text = "⬆️ Upgrades", color = Color3.fromRGB(255, 160, 40) },
}) do
	local menuButton = button({
		Text = entry.text, BackgroundColor3 = entry.color, Size = UDim2.new(1, 0, 0, 56), LayoutOrder = index, Parent = menu,
	})
	menuButton.Activated:Connect(function()
		togglePanel(entry.name)
	end)
end

-- State syncing ------------------------------------------------------------

local function countUnique()
	local owned = {}
	local total = 0
	for key, count in pairs(state.cards) do
		local card = CardData.ParseKey(key)
		if card and count > 0 and not owned[card.id] then
			owned[card.id] = true
			total += 1
		end
	end
	return total
end

local function onState(newState)
	if not newState then
		return
	end
	state = newState
	collectionLabel.Text = ("📖 %d/%d"):format(countUnique(), #CardData.Cards)
	for name, refresh in pairs(panelRefreshers) do
		if panels[name].Visible then
			refresh()
		end
	end
end

remotes.StateChanged.OnClientEvent:Connect(onState)
task.spawn(function()
	onState(remotes.GetState:InvokeServer())
end)

task.spawn(function()
	local coins = player:WaitForChild("leaderstats"):WaitForChild("Coins")
	local function onCoins()
		coinsLabel.Text = "🪙 " .. formatNumber(coins.Value)
		if panels.Packs.Visible then
			refreshPacks()
		end
		if panels.Upgrades.Visible then
			refreshUpgrades()
		end
	end
	coins.Changed:Connect(onCoins)
	onCoins()
end)

-- Open the shop on join so new players know what to do.
togglePanel("Packs")
