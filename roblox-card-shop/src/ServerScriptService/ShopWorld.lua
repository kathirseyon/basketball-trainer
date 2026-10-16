-- ShopWorld (ModuleScript in ServerScriptService)
-- Builds a card shop for each player on their own plot, with display cases
-- and NPC customers who walk in and buy the cards on display.
-- GameServer owns the player data; this module calls back into it through
-- the hooks passed to ShopWorld.Init.

local Debris = game:GetService("Debris")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local CardData = require(ReplicatedStorage:WaitForChild("CardData"))

local ShopWorld = {}

-- Each plot's local +Z faces the street that runs along world z = 0.
local PLOT_ORIGINS = {
	CFrame.new(-120, 0, -90),
	CFrame.new(0, 0, -90),
	CFrame.new(120, 0, -90),
	CFrame.new(-120, 0, 90) * CFrame.Angles(0, math.pi, 0),
	CFrame.new(0, 0, 90) * CFrame.Angles(0, math.pi, 0),
	CFrame.new(120, 0, 90) * CFrame.Angles(0, math.pi, 0),
}

-- Display case spots in shop-local coordinates, in unlock order.
-- `stand` is where a customer stops to look at the case; side cases also
-- have a `via` point in the center aisle so customers don't walk into
-- the middle cases on the way.
local function sideSpot(x, z)
	local standX = x > 0 and 11 or -11
	return { pos = Vector3.new(x, 0, z), stand = Vector3.new(standX, 0, z), via = Vector3.new(0, 0, z) }
end
local CASE_SPOTS = {
	{ pos = Vector3.new(-6, 0, 2), stand = Vector3.new(-6, 0, 5.5) },
	{ pos = Vector3.new(6, 0, 2), stand = Vector3.new(6, 0, 5.5) },
	sideSpot(-15, -9),
	sideSpot(15, -9),
	sideSpot(-15, -3),
	sideSpot(15, -3),
	sideSpot(-15, 8),
	sideSpot(15, 8),
}

local STREET_POINT = Vector3.new(0, 0, 42) -- customers appear and leave here
local DOOR_OUTSIDE = Vector3.new(0, 0, 19)
local DOOR_INSIDE = Vector3.new(0, 0, 11)
local PLAYER_SPAWN = Vector3.new(0, 4, 24)

local SKIN_TONES = {
	Color3.fromRGB(255, 220, 177), Color3.fromRGB(234, 184, 146), Color3.fromRGB(198, 134, 66),
	Color3.fromRGB(141, 85, 36), Color3.fromRGB(94, 59, 35),
}
local SHIRT_COLORS = {
	Color3.fromRGB(220, 60, 60), Color3.fromRGB(60, 120, 220), Color3.fromRGB(60, 180, 90),
	Color3.fromRGB(240, 190, 40), Color3.fromRGB(160, 80, 200), Color3.fromRGB(240, 130, 40),
}
local PANTS_COLORS = {
	Color3.fromRGB(40, 50, 90), Color3.fromRGB(50, 50, 55), Color3.fromRGB(110, 80, 50),
}

local hooks
local plots = {}
local plotByPlayer = {}
local rng = Random.new()

local plotsFolder = Instance.new("Folder")
plotsFolder.Name = "Plots"
plotsFolder.Parent = workspace

-- Helpers ------------------------------------------------------------------

local function part(parent, origin, props)
	local p = Instance.new("Part")
	p.Anchored = true
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	for key, value in pairs(props) do
		if key ~= "At" then
			p[key] = value
		end
	end
	p.CFrame = origin * CFrame.new(props.At)
	p.Parent = parent
	return p
end

local function textLabel(parent, props)
	local labelObj = Instance.new("TextLabel")
	labelObj.BackgroundTransparency = 1
	labelObj.Font = Enum.Font.FredokaOne
	labelObj.TextScaled = true
	labelObj.TextColor3 = Color3.new(1, 1, 1)
	for key, value in pairs(props) do
		labelObj[key] = value
	end
	labelObj.Parent = parent
	return labelObj
end

local function corner(parent, radius)
	local c = Instance.new("UICorner")
	c.CornerRadius = UDim.new(0, radius)
	c.Parent = parent
end

local function worldPoint(plot, localPos)
	return (plot.origin * CFrame.new(localPos)).Position
end

-- Plot pads ----------------------------------------------------------------

for index, origin in ipairs(PLOT_ORIGINS) do
	local folder = Instance.new("Folder")
	folder.Name = "Plot" .. index
	folder.Parent = plotsFolder

	part(folder, origin, {
		Name = "Pad", Size = Vector3.new(56, 0.1, 64), At = Vector3.new(0, 0.05, 4),
		Color = Color3.fromRGB(120, 125, 135), Material = Enum.Material.Concrete,
	})
	local sign = part(folder, origin, {
		Name = "EmptySign", Size = Vector3.new(14, 4, 0.5), At = Vector3.new(0, 3, 20),
		Color = Color3.fromRGB(60, 60, 70),
	})
	local gui = Instance.new("SurfaceGui")
	gui.Face = Enum.NormalId.Back
	gui.Parent = sign
	textLabel(gui, { Size = UDim2.fromScale(1, 1), Text = "Empty plot" })

	table.insert(plots, {
		origin = origin, folder = folder, emptySign = sign,
		owner = nil, model = nil, casesFolder = nil, customersFolder = nil,
		customers = 0, token = nil,
	})
end

-- Shop building ------------------------------------------------------------

local function buildShop(plot)
	local o = plot.origin
	local model = Instance.new("Model")
	model.Name = "Shop_" .. plot.owner.Name
	model.Parent = plot.folder

	local wallColor = Color3.fromRGB(245, 235, 210)
	local trimColor = Color3.fromRGB(70, 110, 200)

	part(model, o, {
		Name = "Floor", Size = Vector3.new(40, 0.2, 30), At = Vector3.new(0, 0.15, 0),
		Color = Color3.fromRGB(190, 150, 100), Material = Enum.Material.WoodPlanks,
	})
	part(model, o, { Name = "BackWall", Size = Vector3.new(40, 12, 1), At = Vector3.new(0, 6, -15), Color = wallColor })
	part(model, o, { Name = "LeftWall", Size = Vector3.new(1, 12, 30), At = Vector3.new(-20, 6, 0), Color = wallColor })
	part(model, o, { Name = "RightWall", Size = Vector3.new(1, 12, 30), At = Vector3.new(20, 6, 0), Color = wallColor })
	-- Front wall with a 10-stud doorway in the middle.
	part(model, o, { Name = "FrontLeft", Size = Vector3.new(15, 12, 1), At = Vector3.new(-12.5, 6, 15), Color = wallColor })
	part(model, o, { Name = "FrontRight", Size = Vector3.new(15, 12, 1), At = Vector3.new(12.5, 6, 15), Color = wallColor })
	part(model, o, { Name = "DoorTop", Size = Vector3.new(10, 3, 1), At = Vector3.new(0, 10.5, 15), Color = wallColor })
	part(model, o, {
		Name = "Awning", Size = Vector3.new(42, 0.6, 4), At = Vector3.new(0, 12.3, 16.5), Color = trimColor,
	})

	local sign = part(model, o, {
		Name = "Sign", Size = Vector3.new(26, 4.5, 0.5), At = Vector3.new(0, 15, 15.2), Color = trimColor,
	})
	local signGui = Instance.new("SurfaceGui")
	signGui.Face = Enum.NormalId.Back
	signGui.Parent = sign
	textLabel(signGui, {
		Size = UDim2.fromScale(0.95, 0.8), Position = UDim2.fromScale(0.025, 0.1),
		Text = plot.owner.DisplayName .. "'s Card Shop",
	})

	local counter = part(model, o, {
		Name = "Counter", Size = Vector3.new(12, 4, 3), At = Vector3.new(0, 2, -12.5),
		Color = Color3.fromRGB(120, 80, 50), Material = Enum.Material.Wood,
	})
	part(model, o, {
		Name = "Register", Size = Vector3.new(2, 1.5, 1.5), At = Vector3.new(3, 4.75, -12.5),
		Color = Color3.fromRGB(40, 40, 45),
	})
	local counterGui = Instance.new("BillboardGui")
	counterGui.Size = UDim2.fromScale(10, 2)
	counterGui.StudsOffset = Vector3.new(0, 5, 0)
	counterGui.MaxDistance = 60
	counterGui.Parent = counter
	textLabel(counterGui, {
		Size = UDim2.fromScale(1, 1), Text = "Stock your cases from the 📖 Binder!",
		TextStrokeTransparency = 0.4,
	})

	plot.casesFolder = Instance.new("Folder")
	plot.casesFolder.Name = "Cases"
	plot.casesFolder.Parent = model
	plot.customersFolder = Instance.new("Folder")
	plot.customersFolder.Name = "Customers"
	plot.customersFolder.Parent = model
	plot.model = model
end

local function buildCardBillboard(base, key, sellLevel)
	local card, isShiny = CardData.ParseKey(key)
	local rarity = CardData.RarityById[card.rarity]

	local billboard = Instance.new("BillboardGui")
	billboard.Size = UDim2.fromScale(3, 4.2) -- in studs
	billboard.StudsOffset = Vector3.new(0, 4.4, 0)
	billboard.MaxDistance = 80
	billboard.Parent = base

	local frame = Instance.new("Frame")
	frame.Size = UDim2.fromScale(1, 1)
	frame.BackgroundColor3 = Color3.fromRGB(248, 243, 228)
	frame.Parent = billboard
	corner(frame, 8)
	local stroke = Instance.new("UIStroke")
	stroke.Color = rarity.color
	stroke.Thickness = 4
	stroke.Parent = frame

	local art = Instance.new("Frame")
	art.BackgroundColor3 = isShiny and Color3.fromRGB(255, 215, 80) or rarity.color
	art.Position = UDim2.fromScale(0.08, 0.06)
	art.Size = UDim2.fromScale(0.84, 0.5)
	art.Parent = frame
	corner(art, 6)
	textLabel(art, { Size = UDim2.fromScale(0.8, 0.8), Position = UDim2.fromScale(0.1, 0.1), Text = card.icon })

	textLabel(frame, {
		Position = UDim2.fromScale(0.05, 0.58), Size = UDim2.fromScale(0.9, 0.16),
		Text = (isShiny and "✨" or "") .. card.name, TextColor3 = Color3.fromRGB(35, 35, 45),
	})
	textLabel(frame, {
		Position = UDim2.fromScale(0.05, 0.78), Size = UDim2.fromScale(0.9, 0.16),
		Text = "🪙 " .. CardData.GetShopPrice(key, sellLevel), TextColor3 = Color3.fromRGB(30, 140, 60),
	})
end

local function buildEmptyBillboard(base)
	local billboard = Instance.new("BillboardGui")
	billboard.Size = UDim2.fromScale(4, 1.5)
	billboard.StudsOffset = Vector3.new(0, 3, 0)
	billboard.MaxDistance = 60
	billboard.Parent = base
	textLabel(billboard, {
		Size = UDim2.fromScale(1, 1), Text = "Empty", TextColor3 = Color3.fromRGB(200, 200, 210),
		TextStrokeTransparency = 0.4,
	})
end

function ShopWorld.RefreshCases(player)
	local plot = plotByPlayer[player]
	local data = hooks.getData(player)
	if not plot or not data then
		return
	end
	plot.casesFolder:ClearAllChildren()

	local caseCount = math.min(CardData.GetCaseCount(data.upgrades.cases), #CASE_SPOTS)
	for index = 1, caseCount do
		local spot = CASE_SPOTS[index]
		local base = part(plot.casesFolder, plot.origin, {
			Name = "Case" .. index, Size = Vector3.new(3, 3, 3), At = spot.pos + Vector3.new(0, 1.6, 0),
			Color = Color3.fromRGB(90, 60, 40), Material = Enum.Material.Wood,
		})
		part(plot.casesFolder, plot.origin, {
			Name = "Glass", Size = Vector3.new(3.2, 0.3, 3.2), At = spot.pos + Vector3.new(0, 3.25, 0),
			Color = Color3.fromRGB(180, 230, 255), Material = Enum.Material.Glass, Transparency = 0.4,
		})

		local key = data.display[tostring(index)]
		local prompt = Instance.new("ProximityPrompt")
		prompt.ObjectText = "Display Case"
		prompt.HoldDuration = 0
		prompt.MaxActivationDistance = 8
		prompt.RequiresLineOfSight = false
		if key then
			buildCardBillboard(base, key, data.upgrades.sell)
			prompt.ActionText = "Take Back"
		else
			buildEmptyBillboard(base)
			prompt.ActionText = "Stock Card"
		end
		prompt.Parent = base
		prompt.Triggered:Connect(function(who)
			if who ~= player then
				return
			end
			if key then
				hooks.takeBack(player, index)
			else
				hooks.openBinder(player)
			end
		end)
	end
end

-- Customers ----------------------------------------------------------------

local function bubble(model, text)
	local head = model:FindFirstChild("Head")
	if not head then
		return
	end
	local old = head:FindFirstChild("Bubble")
	if old then
		old:Destroy()
	end
	local billboard = Instance.new("BillboardGui")
	billboard.Name = "Bubble"
	billboard.Size = UDim2.fromScale(2.2, 2.2)
	billboard.StudsOffset = Vector3.new(0, 2.4, 0)
	billboard.Parent = head
	textLabel(billboard, { Size = UDim2.fromScale(1, 1), Text = text })
	Debris:AddItem(billboard, 2.5)
end

local function makeCustomer(plot)
	local ok, model = pcall(function()
		local description = Instance.new("HumanoidDescription")
		local skin = SKIN_TONES[rng:NextInteger(1, #SKIN_TONES)]
		local pants = PANTS_COLORS[rng:NextInteger(1, #PANTS_COLORS)]
		description.HeadColor = skin
		description.LeftArmColor = skin
		description.RightArmColor = skin
		description.TorsoColor = SHIRT_COLORS[rng:NextInteger(1, #SHIRT_COLORS)]
		description.LeftLegColor = pants
		description.RightLegColor = pants
		return Players:CreateHumanoidModelFromDescription(description, Enum.HumanoidRigType.R15)
	end)
	if not ok then
		warn("[CardShop] Couldn't create customer: " .. tostring(model))
		return nil
	end

	model.Name = "Customer"
	local humanoid = model:FindFirstChildOfClass("Humanoid")
	humanoid.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
	humanoid.WalkSpeed = 10
	model:PivotTo(plot.origin * CFrame.new(STREET_POINT + Vector3.new(0, 3, 0)))
	model.Parent = plot.customersFolder
	local root = model:FindFirstChild("HumanoidRootPart")
	if root then
		pcall(function()
			root:SetNetworkOwner(nil) -- server controls movement, so it stays smooth
		end)
	end
	return model, humanoid
end

-- Walks to a point, giving up after a timeout or if the NPC was removed.
local function walkTo(model, humanoid, worldPos)
	if not model.Parent then
		return false
	end
	local arrived = false
	local connection = humanoid.MoveToFinished:Connect(function()
		arrived = true
	end)
	humanoid:MoveTo(worldPos)
	local elapsed = 0
	while not arrived and elapsed < 10 and model.Parent do
		elapsed += task.wait(0.1)
	end
	connection:Disconnect()
	return model.Parent ~= nil
end

local function runCustomer(plot, token)
	plot.customers += 1
	local model, humanoid = makeCustomer(plot)
	if model then
		local owner = plot.owner
		local function go(localPos)
			return plot.token == token and walkTo(model, humanoid, worldPoint(plot, localPos))
		end

		if go(DOOR_OUTSIDE) and go(DOOR_INSIDE) then
			local data = hooks.getData(owner)
			local stocked = {}
			if data then
				for index = 1, math.min(CardData.GetCaseCount(data.upgrades.cases), #CASE_SPOTS) do
					if data.display[tostring(index)] then
						table.insert(stocked, index)
					end
				end
			end

			if #stocked == 0 then
				bubble(model, "😞")
				task.wait(1.5)
			else
				local caseIndex = stocked[rng:NextInteger(1, #stocked)]
				local spot = CASE_SPOTS[caseIndex]
				if spot.via then
					go(spot.via)
				end
				if go(spot.stand) then
					bubble(model, "🤔")
					task.wait(2)
					-- Someone else may have bought it while we walked over.
					local bought = plot.token == token and hooks.sellFromCase(owner, caseIndex)
					bubble(model, bought and "💰" or "😞")
					task.wait(1)
				end
				if spot.via then
					go(spot.via)
				end
			end
			go(DOOR_INSIDE)
			go(DOOR_OUTSIDE)
			go(STREET_POINT)
		end
		model:Destroy()
	end
	if plot.token == token then
		plot.customers -= 1
	end
end

local function customerLoop(plot, token)
	while plot.token == token do
		local data = hooks.getData(plot.owner)
		local interval = CardData.GetCustomerInterval(data and data.upgrades.ads or 0)
		task.wait(interval * rng:NextNumber(0.7, 1.3))
		if plot.token == token and plot.customers < CardData.MAX_CUSTOMERS then
			task.spawn(runCustomer, plot, token)
		end
	end
end

-- Public API ---------------------------------------------------------------

function ShopWorld.Init(newHooks)
	hooks = newHooks
end

function ShopWorld.SendHome(player)
	local plot = plotByPlayer[player]
	local character = player.Character
	if plot and character then
		character:PivotTo(plot.origin * CFrame.new(PLAYER_SPAWN))
	end
end

-- Gives the player the first free plot and builds their shop.
function ShopWorld.Claim(player)
	for _, plot in ipairs(plots) do
		if not plot.owner then
			plot.owner = player
			plot.token = {}
			plot.customers = 0
			plotByPlayer[player] = plot
			plot.emptySign.Parent = nil
			buildShop(plot)
			ShopWorld.RefreshCases(player)
			ShopWorld.SendHome(player)
			task.spawn(customerLoop, plot, plot.token)
			return true
		end
	end
	return false
end

function ShopWorld.Release(player)
	local plot = plotByPlayer[player]
	if not plot then
		return
	end
	plotByPlayer[player] = nil
	plot.token = nil
	plot.owner = nil
	if plot.model then
		plot.model:Destroy()
		plot.model = nil
	end
	plot.emptySign.Parent = plot.folder
end

return ShopWorld
