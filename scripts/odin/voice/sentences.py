"""The lines Grandpa's own voice is trained on: what an assistant actually says.

Deterministic (seeded): the same list every time, so a half-finished dataset
can be resumed. About 1,000 lines, ~50 characters each, chosen to cover:

* what Grandpa says every day (times, numbers, apps, reminders, confirmations);
* every English sound, through a set of phonetically varied general sentences;
* questions, exclamations and lists, so the voice learns rising and falling tones;
* a little Thanglish, written the way Grandpa's replies spell it.
"""

from __future__ import annotations

import random

SEED = 20261119

APPS = [
    "Chrome",
    "Notepad",
    "VS Code",
    "Spotify",
    "File Explorer",
    "Word",
    "Excel",
    "PowerPoint",
    "Calculator",
    "the terminal",
    "Settings",
    "WhatsApp",
    "Telegram",
    "Outlook",
    "the camera",
    "Paint",
    "Task Manager",
    "OBS",
    "Blender",
    "Discord",
]
PLACES = [
    "Bengaluru",
    "Chennai",
    "Salem",
    "Madiwala",
    "BTM Layout",
    "Coimbatore",
    "Madurai",
    "Mysuru",
    "Hyderabad",
    "Mumbai",
    "Delhi",
    "Pondicherry",
]
NUMBERS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "fifteen",
    "twenty",
    "twenty five",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy five",
    "eighty",
    "ninety",
    "a hundred",
]
TIMES = [
    "six in the morning",
    "seven thirty",
    "a quarter past eight",
    "nine o'clock",
    "half past ten",
    "eleven forty five",
    "noon",
    "two in the afternoon",
    "four fifteen",
    "six pm",
    "eight in the evening",
    "ten at night",
    "midnight",
]
DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "today",
    "tomorrow",
    "this weekend",
    "next week",
]
TASKS = [
    "your interview preparation",
    "the electricity bill",
    "a call with your sister",
    "your MCA exam revision",
    "the catering website",
    "a walk",
    "drinking water",
    "the project review",
    "your dentist appointment",
    "buying groceries",
    "the GitHub pull request",
    "your morning workout",
    "the team meeting",
    "backing up your laptop",
    "paying the rent",
    "the YouTube upload",
]
WEATHER = [
    "clear skies",
    "light rain",
    "a thunderstorm",
    "a cloudy afternoon",
    "strong winds",
    "a hot and humid day",
    "a cool breeze",
    "heavy showers",
]

TEMPLATES = [
    "I have opened {app} for you.",
    "Opening {app} now.",
    "{app} is not responding. Shall I close it?",
    "Do you want me to close {app}?",
    "I could not find {app} on this computer.",
    "{app} is already open on your second screen.",
    "The volume is now at {num} percent.",
    "Brightness set to {num} percent.",
    "Your battery is at {num} percent, so please plug in the charger.",
    "Your battery is at {num} percent. You have plenty of time.",
    "It is {time} right now.",
    "I will remind you about {task} at {time}.",
    "Reminder: {task}, {day} at {time}.",
    "You asked me to remind you about {task}.",
    "Shall I move {task} to {day}?",
    "In {place}, it is {num} degrees with {weather}.",
    "Tomorrow in {place}, expect {weather}.",
    "The weather in {place} looks like {weather} this evening.",
    "I found {num} new emails since {time}.",
    "There are {num} files in your downloads folder.",
    "This will delete {num} files. Are you sure?",
    "I saved the note about {task}.",
    "You have {num} reminders for {day}.",
    "Your next meeting is {day} at {time}.",
    "Downloading the update. About {num} minutes left.",
    "The build finished in {num} seconds.",
    "The tests passed. {num} of them ran.",
    "{num} tests failed. Do you want to see the first error?",
    "Connected to your phone. The signal is good.",
    "Do you want me to read it out, or show it on screen?",
]

GENERAL = [
    # Phonetically varied lines (written for this project, any accent welcome).
    "The quick brown fox jumps over the lazy dog.",
    "A wise old man sat quietly under the banyan tree.",
    "She sells sea shells by the sea shore every summer.",
    "Bright vivid colours filled the morning sky above the hills.",
    "Please measure the flour carefully before you add the water.",
    "The judge gave a short, fair answer to every question.",
    "Thick fog rolled over the valley just before dawn.",
    "A cup of filter coffee is the best way to start the day.",
    "The children laughed and chased the kite across the field.",
    "Thunder rumbled far away, and the rain began to fall.",
    "We should treasure the small moments with our family.",
    "The machine hummed softly while the engineer checked the gauge.",
    "Yellow leaves drifted down onto the quiet village road.",
    "Every journey begins with a single, careful step.",
    "The pilot checked the weather before the long flight.",
    "Fresh jasmine flowers were sold at the temple gate.",
    "He fixed the broken chair with glue, nails and patience.",
    "Our neighbour plays the veena beautifully every evening.",
    "The old clock in the hall struck twelve at midnight.",
    "Choose your words wisely, because words can heal or hurt.",
    "Knowledge grows when it is shared with others.",
    "The zebra and the giraffe drank water from the same pond.",
    "A gentle voice can calm even the angriest heart.",
    "The bus was late, so we walked to the station in the rain.",
    "Measure twice and cut once, my grandfather always said.",
    "The museum showed ancient coins, statues and jewellery.",
    "Rivers rise quickly during the monsoon months.",
    "The scientist explained the theory with a simple example.",
    "Quietly, the cat crept towards the unsuspecting pigeon.",
    "Hard work and honesty never go out of fashion.",
    "The shop near the junction sells the best idli in town.",
    "Thirty three thousand three hundred and thirty three.",
    "Whether the weather is warm or cold, we will go out.",
    "The usual route was blocked, so we took the bypass.",
    "Joyful music echoed through the wedding hall all night.",
    "Patience is not the ability to wait, but how you wait.",
    "His voice was deep, calm and full of quiet confidence.",
    "The thief vanished through the window without a sound.",
    "Vegetables, fruits and grains keep the body strong.",
    "Learning a new language opens a door to a new world.",
    "Wash the rice three times before you cook it.",
    "The garage door squeaked loudly as it opened.",
    "Exactly at sunrise, the birds began to sing.",
    "A long queue formed outside the cinema on Friday.",
    "The professor's lecture on physics was surprisingly fun.",
    "Mangoes taste sweetest in the middle of May.",
    "The ship sailed north through the choppy water.",
    "Our village festival brings everyone together once a year.",
    "A smooth road makes even a long drive pleasant.",
    "The truth is usually simpler than we imagine.",
]

ASSISTANT = [
    "Good morning, Captain. How did you sleep?",
    "Good evening, Captain. What shall we work on tonight?",
    "Hello! I am Grandpa, your assistant on this computer.",
    "Of course. Give me a moment.",
    "Done. Anything else?",
    "I am not sure I understood. Could you say that again?",
    "That sounds risky. Do you want me to go ahead?",
    "I will not do that without your permission.",
    "Okay, I have cancelled it. Nothing was changed.",
    "Let me think about that for a second.",
    "Here is what I found.",
    "I could not reach the internet. I will use my local voice for now.",
    "I am listening.",
    "Sorry, I did not catch that.",
    "Yes, Captain.",
    "No problem at all.",
    "Take a break. You have been working for two hours.",
    "Drink some water. It has been a while.",
    "Your laptop is getting warm. Shall I close a few programs?",
    "The screen is locked. See you soon.",
    "Shutting down in one minute. Save your work.",
    "I have paired with your phone. Say hello from there.",
    "Your phone asked me to open Chrome. Do you allow it?",
    "I can see a dialog asking to save the file. Shall I press save?",
    "The window in front is Visual Studio Code.",
    "I read the page. It is about local AI assistants.",
    "Hmm, that is interesting.",
    "Well done! That was a tough one.",
    "Don't worry. We will fix it step by step.",
    "First, let us check the error message.",
    "The fix is ready. Please run the tests once.",
    "I have pushed the change to GitHub.",
    "The pull request was merged.",
    "Memory saved: you prefer short answers in the morning.",
    "I don't know that yet. Do you want me to look it up?",
    "Shall I play some music while you work?",
    "Playing your focus playlist on Spotify.",
    "Paused.",
    "Resuming.",
    "Muted. Say Hey Grandpa when you need me.",
    "Wise words take time. Let me find the right ones.",
    "Remember, slow progress is still progress.",
    "Every expert was once a beginner.",
    "One step at a time, Captain. We are getting there.",
    "Is there anything else you would like me to do?",
    "Goodnight, Captain. Rest well.",
]

THANGLISH = [
    "Vanakkam Captain, eppadi irukeenga?",
    "Seri, Chrome open panren.",
    "Volume thirty ku vechiten.",
    "Unga notes la save panniten.",
    "Indha file delete pannatuma? Confirm pannunga.",
    "Konjam wait pannunga, check panren.",
    "Battery kammiya irukku, charger podunga.",
    "Naalaiku kaalaila ombodhu manikku reminder vechiten.",
    "Romba nalla irukku, super ah pannirukeenga.",
    "Enna help venum Captain?",
    "Sari, adhu mudinjiduchu.",
    "Network illa, local voice la pesuren.",
    "Paattu podatuma?",
    "Thoonga poreengala? Good night Captain.",
    "Inniku Bengaluru la mazhai varum pola irukku.",
    "Kavalai padadheenga, step by step fix pannalam.",
]


def build(seed: int = SEED, templated: int = 760) -> list[str]:
    rng = random.Random(seed)
    lines = list(GENERAL) + list(ASSISTANT) + list(THANGLISH)
    seen = set(lines)
    tries = 0
    while len(lines) < len(GENERAL) + len(ASSISTANT) + len(THANGLISH) + templated:
        tries += 1
        if tries > 50_000:
            break
        line = rng.choice(TEMPLATES).format(
            app=rng.choice(APPS),
            num=rng.choice(NUMBERS),
            time=rng.choice(TIMES),
            task=rng.choice(TASKS),
            day=rng.choice(DAYS),
            place=rng.choice(PLACES),
            weather=rng.choice(WEATHER),
        )
        line = line[0].upper() + line[1:]
        if line not in seen:
            seen.add(line)
            lines.append(line)
    rng.shuffle(lines)
    return lines


if __name__ == "__main__":
    out = build()
    print(len(out), "lines,", sum(map(len, out)), "characters")
