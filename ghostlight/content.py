from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

from . import novelty


@dataclass(frozen=True)
class Niche:
    key: str
    label: str
    kicker: str
    promise: str
    category_id: str
    subjects: list[str]
    lenses: list[str]
    realms: list[str]
    images: list[str]
    details: list[str]
    concepts: list[str]
    metaphors: list[str]
    scales: list[str]
    reframes: list[str]
    questions: list[str]
    closings: list[str]
    palettes: list[str]
    styles: list[str]
    moods: list[str]


@dataclass(frozen=True)
class Format:
    key: str
    label: str
    intent: str
    instructions: str
    headings: list[str]
    signature: str
    suited: tuple[str, ...] = ("short", "long")


NICHES: dict[str, Niche] = {
    "cosmic": Niche(
        key="cosmic",
        label="Deep sky, deep time",
        kicker="COSMIC",
        promise="essays about scale, absence and the long quiet above us",
        category_id="28",
        subjects=[
            "the Voyager probes",
            "the oldest light in the sky",
            "the Boötes Void",
            "Europa's buried ocean",
            "the dust between stars",
            "the slow death of the Sun",
            "the far side of the Moon",
            "the methane lakes of Titan",
            "the Oort cloud",
            "the first stars",
            "the cosmic microwave background",
            "the Andromeda collision",
            "the sound of a black hole",
            "the Kuiper Belt",
            "the Pillars of Creation",
            "the heat death of the universe",
            "the Great Attractor",
            "the silence of space",
            "Mars' dust storms",
            "the Arecibo message",
            "gravitational lensing",
            "the shape of the Milky Way",
            "the last star",
            "interstellar wind",
        ],
        lenses=[
            "scale",
            "deep time",
            "absence",
            "distance",
            "first light",
            "silence",
            "the edge of the map",
            "what the instrument misses",
            "patience",
            "returning light",
            "the shape of nothing",
            "listening",
            "proportion",
            "the long now",
        ],
        realms=[
            "the far dark",
            "the space between stars",
            "the edge of the observable",
            "the long quiet",
            "the light-years between us",
            "the corridors of the solar system",
        ],
        images=[
            "a white forest of dead stars",
            "a planet turning its back to the sun",
            "a single point of light older than the ground you stand on",
            "a river of dust with no banks",
            "an ocean of night with one lamp in it",
            "a silence with a temperature",
        ],
        details=[
            "how the light arrives after the thing that made it is gone",
            "the way distance turns every object into a memory",
            "how the dark is not empty but patient",
            "the way one instrument can redraw the size of everything",
            "how the oldest signal sounds like weather",
            "the small error that turns a planet into a moon",
        ],
        concepts=[
            "deep time",
            "the long quiet",
            "the arithmetic of distance",
            "absence as a material",
            "the patience of light",
            "a scale that refuses the body",
            "the shape of the unseen",
            "cosmic loneliness",
            "the ledger of light",
            "proportion",
        ],
        metaphors=[
            "a cathedral with the lights off",
            "a letter that takes four years to arrive",
            "a room where the clock runs slow",
            "an ocean with no shore",
            "a conversation held through a wall",
            "a map drawn from the sound of footsteps",
        ],
        scales=[
            "the width of a human hair",
            "the distance to the Moon",
            "the age of a mayfly",
            "the life of the Sun",
            "the span of a human hand",
            "the space between two galaxies",
        ],
        reframes=[
            "a question about attention",
            "an argument between light and time",
            "a lesson in proportion",
            "a story about waiting",
            "a way of measuring the dark",
            "a quiet negotiation with distance",
        ],
        questions=[
            "What would it mean to measure a place by its silence?",
            "Who decided where the edge was?",
            "What are we not seeing because we are looking for a thing and not a relationship?",
            "If the light outlives the source, which one is the event?",
            "How much of what we call empty is simply unlit?",
        ],
        closings=[
            "Somewhere, the process continues without an audience. It always has.",
            "There is no ending out here, only a change in the light.",
            "Leave a light on for the things that do not need us to be watching.",
            "Nothing is solved. Something is seen.",
            "The last frame is not the end. It is just where the light happens to stop.",
            "Walk home slowly. The sky is larger than it was an hour ago.",
        ],
        palettes=["cosmic_indigo", "cosmic_violet", "cosmic_cold"],
        styles=["aurora", "dusk", "neon"],
        moods=["wonder", "weightless"],
    ),
    "deep_sea": Niche(
        key="deep_sea",
        label="The world below the light line",
        kicker="DEEP WATER",
        promise="quiet dispatches from the least visited place on Earth",
        category_id="27",
        subjects=[
            "the Mariana snailfish",
            "bioluminescent plankton",
            "the whale fall",
            "the Challenger Deep",
            "the midnight zone",
            "hydrothermal vents",
            "the Greenland shark",
            "the giant squid",
            "the deep scattering layer",
            "Antarctic krill",
            "the abyssal plain",
            "sperm whale song",
            "the ocean's twilight zone",
            "seafloor sediment",
            "the yeti crab",
            "the dumbo octopus",
            "methane seeps",
            "the sound channel of the deep",
            "the lost city vents",
            "the tides",
            "the oldest seawater",
            "the pressure at four thousand meters",
            "the glass squid",
            "the whale highway",
        ],
        lenses=[
            "pressure",
            "darkness",
            "patience",
            "the light line",
            "sound",
            "cold",
            "the unvisited",
            "adaptation",
            "what falls",
            "the weight of water",
            "the edge of the map",
            "deep time",
        ],
        realms=[
            "the midnight zone",
            "beneath the light line",
            "the abyssal plain",
            "the water column",
            "the deep scattering layer",
            "the cold dark",
        ],
        images=[
            "a snow of dead plankton falling through black water",
            "a light with no sun behind it",
            "a forest of white tubes breathing in the cold",
            "a plain of sediment older than the mountains",
            "a bone-white shell turning in the current",
            "a shape in the dark that answers in light",
        ],
        details=[
            "how the pressure writes itself into bone",
            "the way sound travels farther than sight",
            "how the cold slows everything except need",
            "the way a single dead whale becomes a city",
            "how light is manufactured rather than borrowed",
            "the silence that is not silence but a different frequency",
        ],
        concepts=[
            "pressure",
            "the light line",
            "marine snow",
            "the patience of cold",
            "a darkness with a floor",
            "the economy of scarcity",
            "the long fall",
            "an architecture of water",
            "the unvisited",
            "depth",
        ],
        metaphors=[
            "a cathedral with the lights off",
            "a city built on a corpse",
            "a room where gravity leans",
            "a snowfall that never lands",
            "a lamp with no switch",
            "an attic of the world",
        ],
        scales=[
            "the height of a person",
            "the depth of the deepest trench",
            "the length of a blue whale",
            "the span of a human life",
            "the distance sound travels in water",
            "the width of a single cell",
        ],
        reframes=[
            "a question about attention",
            "a lesson in pressure",
            "a story about patience",
            "a different kind of light",
            "a way of keeping time without a sun",
            "an argument against surfaces",
        ],
        questions=[
            "What would a map look like if it mapped pressure instead of place?",
            "How do you measure a darkness that has a floor?",
            "What grows where nothing is supposed to grow?",
            "If sound is the local language, what are we shouting into?",
            "How much of the ocean is a verb rather than a place?",
        ],
        closings=[
            "Somewhere below, the snow keeps falling without a sky.",
            "The dark is not empty. It is simply occupied on its own terms.",
            "Leave a light on, even where no one will see it.",
            "Nothing is solved. Something is seen.",
            "The deep does not need our attention. It has its own.",
            "Walk home slowly. The ground is thinner than it was an hour ago.",
        ],
        palettes=["deep_teal", "deep_ink", "cosmic_cold"],
        styles=["tide", "ink", "aurora"],
        moods=["hush", "weightless"],
    ),
    "forgotten_history": Niche(
        key="forgotten_history",
        label="What the record left in the margin",
        kicker="THE MARGIN",
        promise="small essays about what the archive kept and what it quietly dropped",
        category_id="27",
        subjects=[
            "the Antikythera mechanism",
            "the Uluburun shipwreck",
            "the library of Timbuktu",
            "the Benin bronzes",
            "the Sogdian merchants",
            "the year without a summer",
            "the Swahili coast",
            "the city of Cahokia",
            "the Inca quipu",
            "the Ottoman tulip craze",
            "the Minoan eruption",
            "the Silk Road's middle",
            "the Cathars",
            "the Bactrian gold",
            "the Rosetta Stone",
            "the Norse settlement of Greenland",
            "the Aztec chinampas",
            "the Great Dying",
            "the medieval warm period",
            "the spice routes",
            "the first printed news",
            "the dead letter office",
            "the margins of the map",
            "the Domesday Book",
        ],
        lenses=[
            "the margin",
            "the ledger",
            "omission",
            "inheritance",
            "the loser's archive",
            "objects without names",
            "paperwork",
            "the weather",
            "distance",
            "translation",
            "the second draft",
            "what survives",
            "provenance",
            "the drawer",
        ],
        realms=[
            "the margin of the record",
            "the archive's back room",
            "the century between wars",
            "the last page of the ledger",
            "the places the map left blank",
            "the second draft of history",
        ],
        images=[
            "a shipping manifest with one name scratched out",
            "a bronze head wrapped in newspaper",
            "a ledger that balances too neatly",
            "a map with a coastline that no longer exists",
            "a letter filed under the wrong century",
            "a room of objects with no labels",
        ],
        details=[
            "how the record is shaped by who was allowed to write",
            "the way an object outlives the language that named it",
            "how a number can be true and still lie",
            "the way trade routes carry ideas like weather",
            "how a single missing page changes the whole book",
            "the way the victor's handwriting gets neater",
        ],
        concepts=[
            "the margin",
            "provenance",
            "the second draft",
            "an archive of omission",
            "the weather of empire",
            "a ledger of small decisions",
            "translation loss",
            "the inheritance of objects",
            "paperwork",
            "what survives",
        ],
        metaphors=[
            "a room with one wall missing",
            "a ledger with a page torn out",
            "a map folded along the wrong river",
            "a house built from its own receipts",
            "a conversation overheard through a door",
            "a museum with the lights half on",
        ],
        scales=[
            "a single page",
            "a century of record-keeping",
            "the length of a trade route",
            "the life of an object",
            "the distance between two translations",
            "the weight of a bronze head",
        ],
        reframes=[
            "a question about power",
            "a lesson in omission",
            "a story about who gets to write",
            "a way of reading the blank spaces",
            "an argument with the archive",
            "a different kind of inheritance",
        ],
        questions=[
            "Who decided what counted as an event?",
            "What would the margin say if it could file a complaint?",
            "How many histories are missing because the paper was expensive?",
            "If an object survives and its language does not, which one is the artifact?",
            "What are we leaving out now that will look obvious later?",
        ],
        closings=[
            "The record closes. The margin stays open.",
            "Somewhere, an object is still waiting for its label.",
            "Leave a light on for the things that were filed away.",
            "Nothing is solved. Something is seen.",
            "The past is not behind us. It is filed beside us.",
            "Walk home slowly. The street names are older than they look.",
        ],
        palettes=["heritage_sepia", "heritage_rust", "cosmic_indigo"],
        styles=["paper", "ink", "ember"],
        moods=["sepia", "tender"],
    ),
    "human_mind": Niche(
        key="human_mind",
        label="The quiet machinery of being a person",
        kicker="THE INNER WEATHER",
        promise="gentle essays about attention, memory, and the rooms behind the voice",
        category_id="27",
        subjects=[
            "the default mode network",
            "deja vu",
            "the tip-of-the-tongue state",
            "nostalgia",
            "the inner critic",
            "attention residue",
            "loneliness in a crowd",
            "the psychology of waiting",
            "the placebo effect",
            "lucid dreaming",
            "the mere exposure effect",
            "the spotlight effect",
            "the memory of smells",
            "procrastination",
            "the fear of missing out",
            "the stories we tell about luck",
            "the voice in the head",
            "boredom",
            "awe",
            "the end-of-history illusion",
            "habit loops",
            "the need to be understood",
            "the half-second before a decision",
            "the feeling of being watched",
        ],
        lenses=[
            "attention",
            "habit",
            "the pause",
            "the story after the fact",
            "memory's editing",
            "the body's vote",
            "the unseen audience",
            "repetition",
            "the half-second",
            "the shape of a question",
            "loneliness",
            "awe",
        ],
        realms=[
            "the half-second before a decision",
            "the room behind the voice",
            "the small hours",
            "the space between a feeling and its name",
            "the audience in your head",
            "the quiet after a question",
        ],
        images=[
            "a room with a lamp left on",
            "a sentence you almost said",
            "a song you cannot place",
            "a door closing softly in another room",
            "a crowd seen through a window",
            "a hand reaching for a word that isn't there",
        ],
        details=[
            "how memory edits without asking",
            "the way the body knows before the story does",
            "how attention leaves a residue on everything it touches",
            "the way a familiar smell can undo a decade",
            "how the inner critic uses your own voice",
            "the way waiting stretches the room",
        ],
        concepts=[
            "attention",
            "the half-second",
            "memory's editing",
            "the unseen audience",
            "the story after the fact",
            "the body's vote",
            "a borrowed voice",
            "the shape of a habit",
            "nostalgia",
            "the need to be understood",
        ],
        metaphors=[
            "a room where the furniture is rearranged each night",
            "a committee that never meets",
            "a lighthouse with no coast",
            "a house with one room always lit",
            "a letter rewritten after it was sent",
            "a stage with the curtain half open",
        ],
        scales=[
            "a single breath",
            "the length of a held pause",
            "the span of a human life",
            "the half-second before a decision",
            "the distance between two people in a crowd",
            "the weight of a familiar object",
        ],
        reframes=[
            "a question about attention",
            "a lesson in self-forgiveness",
            "a story about the body",
            "a way of listening to yourself",
            "an argument with memory",
            "a different kind of company",
        ],
        questions=[
            "How much of what you call your self is a rehearsal?",
            "Who is the audience when no one is in the room?",
            "If memory edits, which version are you loyal to?",
            "What would change if you treated attention as a place rather than a resource?",
            "How many of your decisions are made before you arrive?",
        ],
        closings=[
            "The room is quiet. You are still here. That is not nothing.",
            "Somewhere, a lamp is left on for the version of you that is still deciding.",
            "Leave a light on for the half-second before the answer.",
            "Nothing is solved. Something is seen.",
            "The inner voice is not a verdict. It is a roommate.",
            "Walk home slowly. The street is doing more than you think.",
        ],
        palettes=["mind_mauve", "mind_blue", "heritage_sepia"],
        styles=["ink", "paper", "dusk"],
        moods=["tender", "midnight"],
    ),
    "quiet_tech": Niche(
        key="quiet_tech",
        label="Invisible systems that hold up the day",
        kicker="INFRASTRUCTURE",
        promise="essays about the unglamorous machinery that makes ordinary life possible",
        category_id="28",
        subjects=[
            "the undersea cable",
            "the leap second",
            "the barcode",
            "the shipping container",
            "the GPS clock",
            "the last mile",
            "the fax machine",
            "the air-gapped room",
            "the DNS root",
            "the power grid's frequency",
            "the cloud",
            "the QR code",
            "the lithium mine",
            "the recommendation engine",
            "the password",
            "the universal product code",
            "the cooling tower",
            "the transformer",
            "the submarine cable repeater",
            "the analog backup",
            "the service worker",
            "the fiber splice",
            "the satellite constellation",
            "the dead letter office",
        ],
        lenses=[
            "infrastructure",
            "maintenance",
            "latency",
            "the invisible handoff",
            "standards",
            "redundancy",
            "the last mile",
            "heat",
            "failure",
            "the protocol",
            "scale",
            "the seam",
        ],
        realms=[
            "the last mile",
            "the room where the internet enters",
            "the seam between systems",
            "the server's small light",
            "the hum of the grid",
            "the invisible handoff",
        ],
        images=[
            "a bundle of glass threads under the sea",
            "a room of blinking lights with no windows",
            "a box on a pole that quietly holds a neighborhood",
            "a cable the width of a garden hose carrying a city",
            "a barcode printed on everything you own",
            "a clock that must be told when to wait",
        ],
        details=[
            "how the cloud is a building with a door",
            "the way a single standard saves a million arguments",
            "how heat is the honest byproduct of thought",
            "the way a small timing error becomes a large problem",
            "how maintenance is a form of authorship",
            "the way a password is a promise with a lock on it",
        ],
        concepts=[
            "latency",
            "the last mile",
            "the protocol",
            "redundancy",
            "the invisible handoff",
            "maintenance",
            "the seam",
            "the standard",
            "heat",
            "the cloud",
        ],
        metaphors=[
            "a cathedral with the lights off",
            "a nervous system made of glass",
            "a city with no mayor",
            "a library that lends itself",
            "a clockwork the size of a country",
            "an attic where the weather is made",
        ],
        scales=[
            "the width of a human hair",
            "the depth of the sea",
            "the length of a continent",
            "the time it takes to blink",
            "the distance of a last mile",
            "the weight of a single cable",
        ],
        reframes=[
            "a question about maintenance",
            "a lesson in standards",
            "a story about distance",
            "a way of seeing the room",
            "an argument for the unglamorous",
            "a different kind of infrastructure",
        ],
        questions=[
            "If the cloud has a door, who is allowed to knock?",
            "How much of modern life is a promise the cable holds?",
            "What would you notice first if the hum stopped?",
            "How many invisible people keep the day running?",
            "When is a standard a convenience and when is it a cage?",
        ],
        closings=[
            "Somewhere, a small light is blinking so the day can happen.",
            "The seam is invisible until it isn't. Then it is the only thing.",
            "Leave a light on for the people on the night shift.",
            "Nothing is solved. Something is seen.",
            "The system is not magic. It is maintenance.",
            "Walk home slowly. The street is held up by strangers.",
        ],
        palettes=["tech_steel", "tech_lime", "cosmic_indigo"],
        styles=["neon", "ink", "aurora"],
        moods=["pulse", "weightless"],
    ),
    "natural_world": Niche(
        key="natural_world",
        label="Other ways of being alive",
        kicker="THE LIVING WORLD",
        promise="essays about the patient, strange intelligence of the living world",
        category_id="27",
        subjects=[
            "the oldest trees",
            "coral spawning",
            "the wood-wide web",
            "barn owls' hearing",
            "the tardigrade",
            "monarch migration",
            "the scent of rain",
            "the queen bee's court",
            "pitcher plants",
            "the lyrebird",
            "mycelium",
            "the arctic tern",
            "the Venus flytrap",
            "whale sharks",
            "the glass frog",
            "the aye-aye",
            "lichen",
            "the immortal jellyfish",
            "the humpback's song",
            "seeds in permafrost",
            "the redwood canopy",
            "the dung beetle",
            "the eel migration",
            "the meadow at night",
        ],
        lenses=[
            "adaptation",
            "patience",
            "cooperation",
            "sensing",
            "seasonal time",
            "the body as instrument",
            "the canopy",
            "the underground",
            "mimicry",
            "hunger",
            "symbiosis",
            "the long wait",
        ],
        realms=[
            "the canopy at dawn",
            "the underground",
            "the turning of the season",
            "the tidal edge",
            "the dark under the leaves",
            "the long migration",
        ],
        images=[
            "a tree holding a forest together underground",
            "a cloud of eggs rising into the current",
            "a bird that navigates by a field it cannot see",
            "a flower shaped like a waiting room",
            "a moss older than the forest around it",
            "a night meadow lit by small negotiations",
        ],
        details=[
            "how a tree can warn its neighbors",
            "the way a seed decides when to wake",
            "how a body can taste the direction of home",
            "the way cooperation looks like weather",
            "how a song changes from ocean to ocean",
            "the way a single season can be a lifetime",
        ],
        concepts=[
            "adaptation",
            "symbiosis",
            "seasonal time",
            "the underground",
            "a body as instrument",
            "the long wait",
            "mimicry",
            "hunger",
            "cooperation",
            "the canopy",
        ],
        metaphors=[
            "a city that shares its water",
            "a clock made of light",
            "a map written in scent",
            "a room that only opens in rain",
            "a conversation between root and fungus",
            "a stage with no audience",
        ],
        scales=[
            "the lifespan of a mayfly",
            "the lifespan of a tree",
            "the length of a migration",
            "the size of a seed",
            "the distance a scent can travel",
            "the span of a season",
        ],
        reframes=[
            "a question about time",
            "a lesson in cooperation",
            "a story about listening",
            "a way of keeping time without a clock",
            "an argument for the slow",
            "a different kind of intelligence",
        ],
        questions=[
            "What does a forest know that a tree cannot?",
            "How do you measure a season from underground?",
            "If a song changes across oceans, who is it for?",
            "What would patience look like if it had a body?",
            "How many conversations are happening in a handful of soil?",
        ],
        closings=[
            "Somewhere, a seed is waiting for a condition we cannot hear.",
            "The forest does not hurry. It arrives on time.",
            "Leave a light on for the things that grow in the dark.",
            "Nothing is solved. Something is seen.",
            "The living world is not a backdrop. It is a colleague.",
            "Walk home slowly. The hedgerow is busier than the road.",
        ],
        palettes=["nature_moss", "nature_bone", "deep_teal"],
        styles=["tide", "paper", "dusk"],
        moods=["bloom", "hush"],
    ),
    "liminal_places": Niche(
        key="liminal_places",
        label="Rooms, roads, and the hours between",
        kicker="IN BETWEEN",
        promise="late-night essays about thresholds, waiting rooms and the almost",
        category_id="24",
        subjects=[
            "the airport at 3 a.m.",
            "the last train",
            "a hotel corridor",
            "the edge of a suburb",
            "the ferry terminal",
            "an empty swimming pool",
            "the space between two time zones",
            "a motorway service station",
            "the waiting room",
            "a lighthouse in winter",
            "the car park at dawn",
            "the back of a theatre",
            "a hospital corridor at night",
            "the shoreline at low tide",
            "an abandoned mall",
            "the stairwell",
            "the departure lounge",
            "a toll booth",
            "the motel sign",
            "a bus shelter in the rain",
            "the room where the internet enters",
            "a border crossing",
            "the hour between seasons",
            "the cul-de-sac",
        ],
        lenses=[
            "waiting",
            "transition",
            "anonymity",
            "the hour",
            "architecture",
            "the threshold",
            "belonging",
            "the almost",
            "absence of people",
            "light",
            "the return",
        ],
        realms=[
            "the hour before the first train",
            "the edge of the car park",
            "the back of the building",
            "the corridor between rooms",
            "the coast at low tide",
            "the departure lounge",
        ],
        images=[
            "a sign still lit for no one",
            "a corridor with one working lamp",
            "a chair that has held a thousand waits",
            "a window reflecting a room you cannot see",
            "a car park with the sea just beyond",
            "a departure board changing its mind",
        ],
        details=[
            "how a place changes when no one is using it",
            "the way fluorescent light flattens a face",
            "how a threshold holds two kinds of time",
            "the way an empty pool is still a pool",
            "how a corridor teaches you about distance",
            "the way a sign outlives its destination",
        ],
        concepts=[
            "the threshold",
            "waiting",
            "anonymity",
            "the almost",
            "transition",
            "the hour",
            "belonging",
            "the return",
            "architecture",
            "absence",
        ],
        metaphors=[
            "a room between two rooms",
            "a sentence waiting for a verb",
            "a map with the destination removed",
            "a stage after the actors leave",
            "a clock with no hands",
            "a letter with no address",
        ],
        scales=[
            "the length of a corridor",
            "the time between trains",
            "the span of a night shift",
            "the distance from the car to the door",
            "the height of a ceiling",
            "the space between two people waiting",
        ],
        reframes=[
            "a question about belonging",
            "a lesson in thresholds",
            "a story about the in-between",
            "a way of measuring the almost",
            "an argument for the unclaimed hour",
            "a different kind of company",
        ],
        questions=[
            "What is a place when no one is in it?",
            "How long can a threshold stay a threshold?",
            "Who belongs in a room designed for passing through?",
            "What would a map of waiting look like?",
            "Why do we remember the hours between events?",
        ],
        closings=[
            "Somewhere, a sign is still lit for no one. It is enough.",
            "The threshold holds. That is its whole job.",
            "Leave a light on for the people between places.",
            "Nothing is solved. Something is seen.",
            "The in-between is not a failure of arrival. It is a room.",
            "Walk home slowly. The night is full of other people's thresholds.",
        ],
        palettes=["liminal_dusk", "liminal_neon", "heritage_sepia"],
        styles=["dusk", "neon", "paper"],
        moods=["midnight", "tender"],
    ),
    "everyday_physics": Niche(
        key="everyday_physics",
        label="The strange physics of ordinary things",
        kicker="ORDINARY FORCES",
        promise="tiny essays that turn a kitchen table into a laboratory",
        category_id="28",
        subjects=[
            "the bubble in a glass",
            "the sound of a kettle",
            "the shape of a raindrop",
            "the cold of evaporation",
            "the light in a soap film",
            "the static in a doorknob",
            "the hum of a fridge",
            "the physics of a paper cut",
            "the color of the sky",
            "the wobble of a coin",
            "the steam above a cup",
            "the way sand flows",
            "the crack in a pavement",
            "the heat from a laptop",
            "the resonance of a wine glass",
            "the drift of a paper plane",
            "the meniscus",
            "the mirror in a spoon",
            "the temperature of a shadow",
            "the path of a lightning bolt",
            "the sound of thunder",
            "the dust in a sunbeam",
            "the weight of a cloud",
            "the edge of a rainbow",
        ],
        lenses=[
            "scale",
            "the ordinary",
            "forces",
            "heat",
            "light",
            "resonance",
            "pressure",
            "time",
            "friction",
            "the invisible",
            "the very small",
            "the very fast",
        ],
        realms=[
            "the surface of a cup of tea",
            "the space between two notes",
            "the sunbeam on the floor",
            "the small distances",
            "the ordinary kitchen",
            "the edge of the visible",
        ],
        images=[
            "a rainbow folded into a film of soap",
            "a sunbeam full of slow traffic",
            "a kettle's small weather system",
            "a coin deciding twice",
            "a shadow slightly colder than the air",
            "a crack that has been traveling for years",
        ],
        details=[
            "how a bubble holds a whole sky",
            "the way heat leaves a room",
            "how a raindrop is less a tear than a compromise",
            "the way resonance picks its favorite note",
            "how a crack is a record of a decision",
            "the way light bends around the edge of a spoon",
        ],
        concepts=[
            "surface tension",
            "resonance",
            "the ordinary",
            "heat",
            "the very small",
            "friction",
            "pressure",
            "the edge of the visible",
            "scale",
            "time",
        ],
        metaphors=[
            "a room where every wall is a mirror",
            "a conversation between heat and air",
            "a clock made of dripping",
            "a map of invisible forces",
            "a small weather system",
            "a letter written in pressure",
        ],
        scales=[
            "the width of a hair",
            "the size of a water molecule",
            "the height of a kitchen",
            "the time of a blink",
            "the speed of sound",
            "the length of a wavelength of light",
        ],
        reframes=[
            "a question about scale",
            "a lesson in the ordinary",
            "a story about forces",
            "a way of seeing the invisible",
            "an argument for attention",
            "a different kind of wonder",
        ],
        questions=[
            "How many invisible forces are holding up this sentence?",
            "What would a map of the ordinary look like?",
            "If a crack is a record, who is reading it?",
            "How do you measure a thing that has no edge?",
            "What else is happening in the time it takes to blink?",
        ],
        closings=[
            "Somewhere, a bubble is holding a sky it will never see.",
            "The ordinary is not simple. It is simply close.",
            "Leave a light on for the forces that hold the day together.",
            "Nothing is solved. Something is seen.",
            "The kitchen is a laboratory with better lighting.",
            "Walk home slowly. The puddles are doing physics.",
        ],
        palettes=["physics_paper", "physics_amber", "tech_steel"],
        styles=["paper", "ink", "aurora"],
        moods=["curious", "weightless"],
    ),
}


FORMATS: dict[str, Format] = {
    "field_note": Format(
        "field_note",
        "Field note",
        "a first-person-plural note written from the edge of the subject",
        "Write a field note from close to the subject. Observations first, interpretation second. "
        "No statistics or dates unless you are certain of them. End with a quiet shift in perspective, "
        "not a summary.",
        ["I. Approach", "II. The Quiet Part", "III. Return"],
        "This is a field note, which is another way of saying: I did not solve it, I only stood near it.",
    ),
    "single_question": Format(
        "single_question",
        "One question, circled",
        "an entire essay built around one narrow, physical question",
        "Build the whole piece around a single question. Circle it from several angles; do not answer it "
        "didactically. The question should feel physical and specific, not abstract filler.",
        ["I. The Question", "II. Circling", "III. The Shape It Leaves"],
        "One question. We will not answer it. We will only turn it until the light catches.",
    ),
    "micro_history": Format(
        "micro_history",
        "Small history",
        "a small history told through objects, margins and paperwork",
        "Tell a small, atmospheric history through objects, margins and paperwork rather than a timeline. "
        "Use only widely established facts; never invent dates, names or events. Leave the grand narrative aside.",
        ["I. Before the Record", "II. What Survived", "III. The Margin"],
        "The dates are less important than the silence between them.",
    ),
    "thought_experiment": Format(
        "thought_experiment",
        "Thought experiment",
        "a disciplined speculation staged in the present tense",
        "Stage a disciplined thought experiment in the present tense. State the rules clearly, follow them "
        "honestly, and return to the ordinary world with a changed sense of proportion.",
        ["I. The Premise", "II. Consequences", "III. The Return"],
        "This is a thought experiment, not a prophecy. The difference matters.",
    ),
    "unsolved_file": Format(
        "unsolved_file",
        "Unsolved file",
        "an open case file that refuses to close",
        "Write like an open case file. Present what is known without inventing evidence. The unresolved "
        "quality is the point; do not manufacture a twist or a culprit.",
        ["I. The File", "II. What Doesn't Fit", "III. Still Open"],
        "The file remains open. That is not a failure. It is the honest condition of the thing.",
    ),
    "myth_audit": Format(
        "myth_audit",
        "Myth audit",
        "a fair examination of a common assumption",
        "Examine a common assumption about the subject. State the received version fairly, then complicate "
        "it. No strawmen, no contrarianism for its own sake. End with what is still true.",
        ["I. The Received Version", "II. What the Evidence Does", "III. After the Myth"],
        "The received version is tidy. Tidiness is not evidence.",
    ),
    "anatomy_of": Format(
        "anatomy_of",
        "Anatomy of a thing",
        "one ordinary thing taken apart gently",
        "Dissect one ordinary thing into three layers: surface, mechanism, and cost or meaning. Stay "
        "concrete. Prefer physical detail over abstraction.",
        ["I. Surface", "II. Mechanism", "III. The Cost"],
        "Take it apart gently. The parts are more interesting than the whole.",
    ),
    "night_dispatch": Format(
        "night_dispatch",
        "Night dispatch",
        "a late-night radio sign-off from somewhere far away",
        "Write an intimate late-night radio dispatch. Use first person plural or a direct address to one "
        "listener. Include a sign-off. It should sound spoken, unhurried, never promotional.",
        ["I. Signal", "II. Interference", "III. Sign-Off"],
        "This is a dispatch from the small hours, where the signal is weak and the truth is mostly weather.",
    ),
    "letter_from": Format(
        "letter_from",
        "Letter from elsewhere",
        "a letter written from an impossible vantage point",
        "Write a letter from an impossible vantage point — a place, an object, a stretch of time. Keep it "
        "intimate and restrained. No science-fiction exposition, no plot.",
        ["I. Arrival", "II. Report", "III. Closing"],
        "Consider this a letter with no return address.",
    ),
    "what_if": Format(
        "what_if",
        "What if",
        "a disciplined speculation that returns to the present",
        "Pose a clear what-if about the subject. Reason through the consequences carefully, then return to "
        "the present with a changed proportion. Do not pretend speculation is fact.",
        ["I. The Premise", "II. Consequences", "III. The Return"],
        "This is a thought experiment, not a prophecy. The difference matters.",
    ),
    "quiet_scale": Format(
        "quiet_scale",
        "Quiet scale",
        "one object, one changed number, a new landscape",
        "Take one object or fact and change a single scale — time, size, distance — until it becomes "
        "strange. Keep the arithmetic honest and the language plain.",
        ["I. One Object", "II. Change the Scale", "III. The New Room"],
        "Change one number, and the ordinary becomes a landscape.",
    ),
    "evening_essay": Format(
        "evening_essay",
        "Evening essay",
        "a slow, personal essay with no journalistic pretense",
        "Write a slow personal essay. Use first person singular sparingly. Favor image, rhythm and a single "
        "unresolved thought over argument or exposition.",
        ["I. A Room", "II. A Thought", "III. The Light Changes"],
        "This is not an argument. It is a way of sitting with something.",
    ),
}


PALETTES: dict[str, dict[str, tuple[int, int, int]]] = {
    "cosmic_indigo": {"bg": (7, 9, 20), "mid": (40, 52, 92), "glow": (232, 177, 76), "accent": (143, 196, 220), "paper": (239, 230, 210)},
    "cosmic_violet": {"bg": (11, 8, 18), "mid": (70, 45, 94), "glow": (217, 127, 87), "accent": (185, 164, 224), "paper": (242, 232, 220)},
    "cosmic_cold": {"bg": (4, 10, 18), "mid": (20, 58, 84), "glow": (160, 214, 205), "accent": (90, 140, 180), "paper": (236, 235, 224)},
    "deep_teal": {"bg": (4, 16, 15), "mid": (15, 63, 70), "glow": (127, 208, 196), "accent": (63, 140, 150), "paper": (232, 228, 212)},
    "deep_ink": {"bg": (5, 10, 16), "mid": (18, 42, 58), "glow": (214, 192, 138), "accent": (95, 147, 168), "paper": (236, 231, 217)},
    "heritage_sepia": {"bg": (20, 16, 11), "mid": (74, 54, 35), "glow": (201, 139, 75), "accent": (138, 106, 79), "paper": (231, 221, 200)},
    "heritage_rust": {"bg": (24, 13, 9), "mid": (92, 43, 30), "glow": (217, 123, 74), "accent": (160, 106, 76), "paper": (239, 226, 205)},
    "mind_mauve": {"bg": (16, 11, 18), "mid": (59, 44, 68), "glow": (212, 168, 106), "accent": (154, 127, 174), "paper": (242, 233, 220)},
    "mind_blue": {"bg": (8, 13, 22), "mid": (34, 50, 79), "glow": (224, 197, 143), "accent": (125, 155, 189), "paper": (238, 232, 218)},
    "tech_steel": {"bg": (7, 11, 14), "mid": (28, 44, 51), "glow": (143, 216, 200), "accent": (93, 142, 163), "paper": (232, 232, 223)},
    "tech_lime": {"bg": (8, 13, 10), "mid": (35, 55, 42), "glow": (200, 217, 138), "accent": (125, 163, 138), "paper": (238, 240, 223)},
    "nature_moss": {"bg": (10, 15, 10), "mid": (42, 58, 36), "glow": (201, 178, 106), "accent": (127, 160, 106), "paper": (236, 230, 210)},
    "nature_bone": {"bg": (18, 17, 13), "mid": (58, 57, 48), "glow": (216, 198, 154), "accent": (143, 156, 132), "paper": (241, 234, 219)},
    "liminal_dusk": {"bg": (11, 12, 20), "mid": (47, 53, 80), "glow": (230, 165, 106), "accent": (142, 136, 176), "paper": (233, 228, 216)},
    "liminal_neon": {"bg": (8, 10, 16), "mid": (23, 42, 60), "glow": (217, 127, 106), "accent": (111, 169, 201), "paper": (234, 229, 217)},
    "physics_paper": {"bg": (20, 18, 13), "mid": (60, 55, 43), "glow": (217, 192, 137), "accent": (143, 157, 148), "paper": (240, 232, 214)},
    "physics_amber": {"bg": (18, 14, 8), "mid": (58, 44, 27), "glow": (227, 169, 92), "accent": (176, 138, 90), "paper": (242, 232, 212)},
}


SMALL_TITLE_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "without",
    "between",
    "over",
    "under",
}


def smart_title(text: str) -> str:
    words = text.strip().split()
    out: list[str] = []
    for i, word in enumerate(words):
        if not word:
            continue
        if word.isupper() and len(word) > 1:
            out.append(word)
            continue
        lower = word.lower()
        if 0 < i < len(words) - 1 and lower in SMALL_TITLE_WORDS:
            out.append(lower)
        else:
            out.append(word[0].upper() + word[1:])
    return " ".join(out)


def niche_keys() -> list[str]:
    return list(NICHES.keys())


def subject_key(value: str) -> str:
    cleaned = novelty.normalize(str(value or ""))
    return re.sub(r"^(?:the|a|an)\s+", "", cleaned).strip()


def get_niche(key: str) -> Niche:
    return NICHES.get(key, NICHES["cosmic"])


def get_format(key: str) -> Format:
    return FORMATS.get(key, FORMATS["field_note"])


def format_choices(fmt: str | None = None) -> list[str]:
    if fmt == "short":
        return [k for k, f in FORMATS.items() if "short" in f.suited]
    if fmt == "long":
        return [k for k, f in FORMATS.items() if "long" in f.suited]
    return list(FORMATS.keys())


def make_brief(
    niches: list[str],
    fmt: str = "short",
    niche_key: str | None = None,
    topic: str | None = None,
    used_subjects: set[str] | None = None,
    used_titles: list[str] | None = None,
    style_override: str | None = None,
    palette_override: str | None = None,
    format_override: str | None = None,
    tone: str = "",
    audience: str = "",
    target_seconds: tuple[int, int] = (28, 46),
    seed: int | None = None,
) -> dict[str, Any]:
    seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)
    rng = random.Random(seed)

    available = [n for n in niches if n in NICHES] or list(NICHES.keys())
    niche_key = niche_key if niche_key in NICHES else rng.choice(available)
    niche = NICHES[niche_key]

    format_key = format_override if format_override in FORMATS else rng.choice(format_choices(fmt))
    fmt_obj = FORMATS[format_key]

    used_subjects = {subject_key(s) for s in (used_subjects or set())}
    subjects = [s for s in niche.subjects if subject_key(s) not in used_subjects]
    if not subjects:
        subjects = niche.subjects
    subject = (topic or "").strip() or rng.choice(subjects)
    subject = re.sub(r"^[\"']|[\"']$", "", subject).strip()

    lens = rng.choice(niche.lenses)
    style = style_override if style_override in STYLE_KEYS else rng.choice(niche.styles)
    palette = palette_override if palette_override in PALETTES else rng.choice(niche.palettes)
    mood = rng.choice(niche.moods)
    scale_a = rng.choice(niche.scales)
    scale_b = rng.choice([s for s in niche.scales if s != scale_a] or niche.scales)

    if len(subject) > 90:
        subject = subject[:87].rsplit(" ", 1)[0] + "…"

    return {
        "nickname": f"{niche.kicker.lower().replace(' ', '-')}-{seed % 9973:04d}",
        "niche": niche.key,
        "niche_label": niche.label,
        "kicker": niche.kicker,
        "promise": niche.promise,
        "format": fmt_obj.key,
        "format_label": fmt_obj.label,
        "format_intent": fmt_obj.intent,
        "format_instructions": fmt_obj.instructions,
        "subject": subject,
        "lens": lens,
        "style": style,
        "palette": palette,
        "mood": mood,
        "realm": rng.choice(niche.realms),
        "image": rng.choice(niche.images),
        "detail": rng.choice(niche.details),
        "concept": rng.choice(niche.concepts),
        "metaphor": rng.choice(niche.metaphors),
        "reframe": rng.choice(niche.reframes),
        "question": rng.choice(niche.questions),
        "scale_a": scale_a,
        "scale_b": scale_b,
        "closing": rng.choice(niche.closings),
        "seed": seed,
        "target_seconds": [int(target_seconds[0]), int(target_seconds[1])],
        "tone": tone,
        "audience": audience,
        "used_titles": (used_titles or [])[:30],
    }


STYLE_KEYS = ["aurora", "ember", "ink", "neon", "paper", "tide", "dusk"]
MOOD_KEYS = ["wonder", "weightless", "hush", "sepia", "tender", "midnight", "pulse", "bloom", "curious"]


def brief_subject(brief: dict[str, Any]) -> str:
    return str(brief.get("subject", "")).strip()


def seeded_choice(niche: Niche, field_name: str, seed: int) -> str:
    rng = random.Random(f"{seed}:{field_name}")
    return rng.choice(getattr(niche, field_name))


GENERIC_OPENERS = [
    "There is {image} at the edge of {realm}, and it is easy to walk past.",
    "Start with {subject}. Not the version in the textbook — the one that refuses to stay still.",
    "Ask ten people about {subject} and you will get ten confident answers. None of them will agree.",
    "The strangest thing about {subject} is not that it exists. It is that we keep forgetting it does.",
    "Somewhere in {realm}, {image} is doing exactly what it has always done.",
    "We have a word for {subject}, which is how you can tell we think we understand it.",
    "Here is a small thing that will not leave me alone: {detail}.",
    "If you could stand at the edge of {realm}, you would notice the quiet first.",
    "This is not a story about {subject}. It is a story about what {subject} does to the way we measure things.",
    "There is a version of {subject} that fits on a postcard. This is not that version.",
    "For most of us, {subject} arrives as a single image. {image_cap}. Then we move on.",
    "Seen through {lens}, {subject} stops being a fact and becomes a weather system.",
]

GENERIC_DEVELOPMENT = [
    "In {realm}, the scale is wrong for human intuition. One detail stays with me: {detail}.",
    "Notice {detail}. Notice, too, how quickly the mind files it away.",
    "The people who study this talk about {concept} the way sailors talk about weather: something you move through, not something you solve.",
    "We call it {concept}. The phrase makes it feel solved. It isn't.",
    "Hold {scale_a} next to {scale_b}. The mind refuses the comparison, then quietly accepts it.",
    "There is a version of this where {subject} is the hero. There is another where it is simply the weather.",
    "The interesting part is not the answer. It is the shape of the question after you carry it around for a while.",
    "If you slow the footage down far enough, {image} becomes a process. Speed is a kind of disguise.",
    "The first impression is {concept}. The second is something closer to {second_concept}.",
    "It would be tidy to say this is about {concept}. Tidiness is not the point.",
    "Think of {metaphor}. Now take away the walls.",
    "There is a small, almost rude question underneath: {question}",
    "The distance between {scale_a} and {scale_b} is not empty. It is {metaphor}.",
    "What we call {concept} may be a story we tell so the numbers feel like a place.",
    "Every so often, {image} turns up where it should not be, and the whole map shivers.",
    "The record is not silent. It is speaking at a frequency we mistook for background.",
    "You can feel the edge of the story here. It is not a wall. It is a change in temperature.",
    "Look at {image} and you are looking at a decision made long before you arrived.",
]

GENERIC_TURNS = [
    "But there is a catch, and it is not a small one.",
    "Then the frame shifts.",
    "Here the story doubles back on itself.",
    "The neat version ends there. The real one keeps going.",
    "This is where the phrase {concept} begins to come apart in your hands.",
    "The obvious reading is {concept}. The quieter reading is that we are looking at {reframe}.",
    "What if the thing we call {concept} is actually {reframe}?",
    "This is the point where scale stops being a number and becomes a feeling.",
    "Now hold that next to {scale_b}, and the comfort goes out of the room.",
    "And yet the question survives the answer.",
]

GENERIC_REFLECTIONS = [
    "Maybe the point was never {concept}. Maybe it was {reframe}.",
    "The mystery is not that it is hidden. The mystery is that it is ordinary, and we still cannot look at it directly.",
    "There is no clean moral here. There is only a shift in proportion.",
    "If this changes anything, it changes the size of the room you think you are standing in.",
    "We are small, but we are the part of the world that can be astonished. That has to count for something.",
    "The story does not resolve. It settles, the way sediment settles.",
    "You do not have to understand it to be changed by it. You only have to stay a little longer.",
    "The most honest response might be a long pause, and then a different question.",
    "What looks like an answer from one distance looks like a beginning from another.",
    "Maybe the room was always this large. We just kept the curtains closed.",
]

CONNECTORS = [
    "There is more.",
    "Follow that thought a little further.",
    "Now widen the frame.",
    "Step back.",
    "Stay with that for a moment.",
]

ANCHORS = [
    "Return to {subject}. It has not moved.",
    "Whatever else this is, it is also a story about {subject}.",
    "The subject was always {subject}, even when the language drifted.",
    "{subject_cap} is the fixed point here.",
    "Keep {subject} in the corner of your eye while the rest of this shifts.",
]


def _fill(template: str, brief: dict[str, Any], rng: random.Random, niche: Niche) -> str:
    concepts = [c for c in niche.concepts if c != brief.get("concept")] or niche.concepts
    values = dict(brief)
    values["second_concept"] = rng.choice(concepts)
    values["image_cap"] = _cap(brief.get("image", ""))
    values["detail_cap"] = _cap(brief.get("detail", ""))
    values["subject_cap"] = _cap(brief.get("subject", ""))
    try:
        return template.format_map(values)
    except (KeyError, ValueError):
        return template


def _cap(text: str) -> str:
    text = text.strip()
    return text[0].upper() + text[1:] if text else text


def compose_offline_script(
    brief: dict[str, Any],
    fmt: str = "short",
    words_min: int = 70,
    words_max: int = 120,
    extra_instructions: str = "",
    recent_titles: list[str] | None = None,
) -> dict[str, Any]:
    """The Muse: a zero-dependency writer used when no language model is available."""
    niche = get_niche(brief["niche"])
    rng = random.Random(f"{brief['seed']}:{brief.get('subject')}:{fmt}:{extra_instructions[:40]}")
    fmt_obj = get_format(brief["format"])

    segments: list[dict[str, str]] = []
    used_templates: set[str] = set()

    opener = _pick_unused(GENERIC_OPENERS, used_templates, rng)
    segments.append({"heading": "", "text": _fill(opener, brief, rng, niche)})

    patterns = [("dev", "reflect"), ("dev", "turn"), ("reflect", "dev")]
    body_count = 2 if fmt == "short" else 7
    for i in range(body_count):
        parts: list[str] = []
        for category in patterns[i % len(patterns)]:
            pool = GENERIC_DEVELOPMENT if category == "dev" else (GENERIC_TURNS if category == "turn" else GENERIC_REFLECTIONS)
            parts.append(_fill(_pick_unused(pool, used_templates, rng), brief, rng, niche))
        if fmt == "long":
            parts.append(_fill(_pick_unused(GENERIC_REFLECTIONS, used_templates, rng), brief, rng, niche))
        if i % 3 == 2:
            parts.append(_fill(_pick_unused(ANCHORS, used_templates, rng), brief, rng, niche))
        text = " ".join(parts)
        if i == 1:
            text = f"{text} {fmt_obj.signature}"
        if i == 3 and fmt == "long":
            text = f"{rng.choice(CONNECTORS)} {text}"
        segments.append({"heading": "", "text": text})

    segments.append({"heading": "", "text": brief["closing"]})
    if fmt == "short" and rng.random() < 0.4:
        segments.append({"heading": "", "text": rng.choice(niche.questions)})

    # keep the piece within a sensible spoken length
    words = sum(len(s["text"].split()) for s in segments)
    guard = 0
    while words < words_min and guard < 12:
        extra = _fill(_pick_unused(list(GENERIC_REFLECTIONS), used_templates, rng), brief, rng, niche)
        segments.insert(-1, {"heading": "", "text": extra})
        words += len(extra.split())
        guard += 1
    while words > words_max and len(segments) > 4:
        segments.pop(-2)
        words = sum(len(s["text"].split()) for s in segments)

    if fmt == "long":
        acts = sorted({0, max(1, len(segments) // 3), max(2, (2 * len(segments)) // 3)})
        for idx, heading in zip(acts, fmt_obj.headings):
            if idx < len(segments):
                segments[idx]["heading"] = heading

    title = offline_title(brief, niche, rng)
    hook = segments[0]["text"]
    description = offline_description(brief, niche, hook)
    tags = offline_tags(brief, niche, rng)

    return {
        "title": title,
        "hook": hook,
        "segments": segments,
        "description": description,
        "tags": tags,
        "thumbnail_text": offline_thumbnail_text(brief, title),
        "visual_style": brief.get("style", "aurora"),
        "music_mood": brief.get("mood", "wonder"),
        "closing_line": brief["closing"],
        "writer": "muse",
        "format": fmt,
        "niche": brief["niche"],
    }


def _pick_unused(pool: list[str], used: set[str], rng: random.Random) -> str:
    available = [item for item in pool if item not in used]
    if not available:
        used.clear()
        available = list(pool)
    choice = rng.choice(available)
    used.add(choice)
    return choice


def offline_title(brief: dict[str, Any], niche: Niche, rng: random.Random) -> str:
    subject = brief["subject"].strip()
    concept = brief["concept"]
    realm = brief["realm"]
    lens = brief["lens"]
    fmt = brief["format"]
    templates = [
        f"What {subject} Leaves Behind",
        f"The Shape of {subject}",
        f"A Field Note on {subject}",
        f"Notes from {realm}",
        f"On the Quiet Life of {subject}",
        f"{subject} and the Shape of {concept}",
        f"The Distance Between {brief['scale_a']} and {brief['scale_b']}",
        f"The Other Side of {concept}",
        f"Seen Through {lens}",
        f"The Light Around {subject}",
        f"The Sound of {subject}",
        f"After {subject}",
        f"The Shape of {realm}",
        f"A Door into {realm}",
        f"The Room at the End of {realm}",
        f"What the Dark Does to {subject}",
        f"Before We Named {concept}",
        f"The Quiet Architecture of {concept}",
        f"An Open Letter to {subject}",
        f"The Question of {subject}",
        f"A World Without {subject}",
        f"Suppose We Took {subject} Seriously",
        f"What {concept} Remembers",
    ]
    format_extras = {
        "micro_history": [f"The Margin of {subject}", f"Filed Under {concept}"],
        "quiet_scale": [f"One Number, {concept}", f"The Scale of {subject}"],
        "letter_from": [f"A Letter from {realm}", f"An Open Letter to {subject}"],
        "anatomy_of": [f"Inside {subject}", f"How {subject} Holds"],
        "evening_essay": [f"The Light Around {subject}", f"A Room Called {concept}"],
        "night_dispatch": [f"A Dispatch from {realm}", f"Notes from {realm}"],
        "single_question": [f"The Question of {subject}", f"What {subject} Asks"],
    }
    templates.extend(format_extras.get(fmt, []))
    for raw in rng.sample(templates, k=min(8, len(templates))):
        title = smart_title(re.sub(r"\s+", " ", raw)).strip(" .")
        if 16 <= len(title) <= 88 and not novelty.cliche_hits(title) and not novelty.continuity_hits(title):
            return title
    fallback = smart_title(f"The Shape of {concept}")
    return fallback[:88]


def novelty_cap(title: str) -> str:
    return title[:1].upper() + title[1:] if title else title


def offline_description(brief: dict[str, Any], niche: Niche, hook: str) -> str:
    first_sentence = re.split(r"(?<=[.!?])\s+", hook.strip())[0]
    if len(first_sentence) > 240:
        first_sentence = first_sentence[:237].rsplit(" ", 1)[0] + "…"
    second = f"A quiet essay on {brief['subject']}, seen through {brief['lens']}."
    return f"{first_sentence}\n\n{second}"


def offline_tags(brief: dict[str, Any], niche: Niche, rng: random.Random) -> list[str]:
    words = [
        brief["niche"].replace("_", " "),
        brief["lens"],
        brief["concept"],
        brief["subject"],
        "essay",
        "quiet",
        "ghostlight studio",
    ]
    tags = []
    for word in words:
        word = str(word).strip().lower()
        if 2 < len(word) <= 40 and word not in tags:
            tags.append(word)
    return tags[:10]


def offline_thumbnail_text(brief: dict[str, Any], title: str) -> str:
    concept = smart_title(brief["concept"])
    if len(concept) > 28:
        words = title.split()
        concept = " ".join(words[:4])
    return concept.upper()


def format_beat_plan(fmt: str) -> list[str]:
    fmt_obj = get_format(fmt)
    return fmt_obj.headings
