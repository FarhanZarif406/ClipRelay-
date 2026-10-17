"""Roman Urdu for the messages the server sends to the page.

The page sends `X-Lang: ur` when its user has chosen Roman Urdu; the common messages people meet (plans, limits,
trial, suspension, keys, channels, downloads) are then answered in Roman Urdu. Rare or technical ones stay in English.
Each pattern is matched against the whole English message; groups carry its numbers and names across.
"""

import re

PATTERNS: list[tuple[str, str]] = [
    # accounts and sign-in
    (r"Incorrect email or password", "Email ya password ghalat hai"),
    (r"Your account is suspended\. Contact the owner\.", "Aap ka account suspend hai. Owner (manager) se rabta karein."),
    (r"Invalid or expired session", "Aap ka session khatam ho gaya hai. Dobara login karein."),
    (r"Not authenticated", "Pehle login karein."),
    (r"Only workspace owners can do this", "Ye kaam sirf owner kar sakta hai."),
    (r"This email already has an account", "Is email ka account pehle se bana hua hai."),
    (r"Email already registered", "Ye email pehle se registered hai."),
    (r"You cannot suspend your own account", "Aap apna account suspend nahi kar sakte."),
    (r"You cannot delete your own account", "Aap apna account delete nahi kar sakte."),
    (r"Account not found", "Account nahi mila."),
    (r"Plan not found", "Plan nahi mila."),
    # plans
    (r"These are for paid members: (.+)\. Switch them off to save, or ask the owner to upgrade your plan\.",
     r"Ye cheezein paid members ke liye hain: \1. Save karne ke liye inhein band karein, ya manager se apna plan upgrade karwayein."),
    (r"(.+) is not part of your plan\. Ask the owner to upgrade it\.", r"\1 aap ke plan mein shamil nahi. Manager se plan upgrade karwayein."),
    (r"Your plan allows (\d+) channels?\. Remove one, or ask the owner to upgrade your plan\.",
     r"Aap ka plan \1 channels tak deta hai. Ek channel hatayein, ya manager se plan upgrade karwayein."),
    (r"The Podcasts workspace is not part of your plan\. Ask the owner to upgrade it\.", "Podcasts aap ke plan mein shamil nahi. Manager se plan upgrade karwayein."),
    (r"Up to (\d+) Buffer keys? can be saved on your plan\. Remove one first\.", r"Aap ke plan par zyada se zyada \1 Buffer key lag sakti hai. Pehle ek hatayein."),
    (r"Up to (\d+) Buffer keys? can be saved\. Remove one first\.", r"Zyada se zyada \1 Buffer keys lag sakti hain. Pehle ek hatayein."),
    (r"Your plan allows (\d+) Buffer accounts? in all, so (\d+) more were not connected: (.+)",
     r"Aap ka plan kul \1 Buffer accounts deta hai, is liye \2 aur accounts nahi jude: \3"),
    (r"You have used today's (\d+) test renders\. They are available again tomorrow\.", r"Aaj ke \1 test render istemal ho chuke hain. Kal phir milenge."),
    (r"A test render is already running\. Wait for it to finish\.", "Ek test render pehle se chal raha hai. Us ke khatam hone ka intezar karein."),
    # PC Helper and cloud editing
    (r"That code is wrong or has expired\. Make a new one on the website: PC Helper → Connect a PC\.",
     "Ye code ghalat hai ya expire ho gaya. Website par naya banayein: PC Helper → Connect a PC."),
    (r"PC not found", "Computer nahi mila."),
    (r"This PC is not connected any more\. Connect it again with a new code from the website\.",
     "Ye computer ab jura hua nahi. Website se naya code le kar dobara jorein."),
    (r"No PC Helper is on for this account and cloud editing is not set up\. Turn the PC Helper on, then press Retry\.",
     "Is account ka PC Helper on nahi aur cloud editing set nahi. PC Helper on karein, phir Retry dabayein."),
    (r"Your plan includes neither PC Helper nor cloud editing\. Ask the owner to upgrade it\.",
     "Aap ke plan mein na PC Helper hai na cloud editing. Manager se plan upgrade karwayein."),
    (r"That is not a key file: Google Cloud gives it as a \.json file\.", "Ye key file nahi: Google Cloud ise .json file ki shakal mein deta hai."),
    # Buffer
    (r"More Buffer keys are not part of your plan: it allows (\d+)\. Ask the owner to upgrade it\.",
     r"Zyada Buffer keys aap ke plan mein shamil nahi: plan \1 key deta hai. Manager se plan upgrade karwayein."),
    (r"This key is already saved\.", "Ye key pehle se save hai."),
    (r"Buffer refused the API key\. Check that it was copied whole and has not expired\.", "Buffer ne API key qubool nahi ki. Dekhein ke poori copy hui hai aur expire nahi hui."),
    (r"That does not look like a Buffer API key\. It should be one line with no spaces\.", "Ye Buffer API key nahi lagti. Key ek line mein, bina space ke honi chahiye."),
    (r"No Buffer API key is saved\.", "Koi Buffer API key save nahi hai."),
    (r"No such Buffer key\.", "Ye Buffer key nahi mili."),
    (r"No such Buffer account\.", "Ye Buffer account nahi mila."),
    (r"The daily limit must be a whole number from 1 to 50\.", "Daily limit 1 se 50 tak ka poora number hona chahiye."),
    (r"Give up to 24 different times of day, each as HH:MM\.", "Din ke zyada se zyada 24 alag waqt dein, har ek HH:MM ki shakal mein."),
    (r"Choose a valid timezone such as Asia/Karachi\.", "Sahi timezone chunein, jaise Asia/Karachi."),
    # YouTube key and channels
    (r"That does not look like a YouTube Data API key\.", "Ye YouTube Data API key nahi lagti."),
    (r"Google did not accept the key: (.+)", r"Google ne key qubool nahi ki: \1"),
    (r"This channel has already been added by (.+)", r"Ye channel pehle hi \1 ne add kar rakha hai."),
    (r"This channel is already being monitored here", "Ye channel yahan pehle se watch ho raha hai."),
    (r"This channel is already being monitored in the (\w+) workspace", r"Ye channel pehle se \1 workspace mein watch ho raha hai."),
    (r"Channel not found", "Channel nahi mila."),
    (r"Video not found", "Video nahi mili."),
    (r"Only skipped videos can be processed by hand", "Sirf skip hui videos haath se process ho sakti hain."),
    # AI models
    (r"No AI model of your own is set up — add one on your Integrations page", "Aap ka apna koi AI model nahi laga — Integrations page par ek add karein."),
    (r"Only owners can manage another account's (AI models|keys)", "Kisi aur account ki keys sirf owner sambhal sakta hai."),
    (r"AI model not found", "AI model nahi mila."),
    (r"Validation failed: (.+)", r"Jaanch nakaam: \1"),
    # system and plans in the pipeline
    (r"Waiting — this account's plan has ended or it is suspended\. The owner can give it a plan\.", "Intezar — is account ka plan khatam hai ya account suspend hai. Owner plan de sakta hai."),
    (r"Daily limit reached: (\d+) of (\d+) (videos|podcasts) already taken today \((.+)\)(.*)", r"Daily limit poori: aaj \2 mein se \1 \3 le li gayin (\4)\5"),
    # editing
    (r"No such preset\.", "Ye preset nahi mila."),
    (r"That is not a YouTube video link\.", "Ye YouTube video ka link nahi hai."),
]
_COMPILED = [(re.compile(rf"^{pattern}$", re.S), replacement) for pattern, replacement in PATTERNS]


def translate(message: str, lang: str | None) -> str:
    """The message in the user's language: Roman Urdu when `lang` is "ur" and the message is a known one."""
    if lang != "ur" or not isinstance(message, str):
        return message
    for pattern, replacement in _COMPILED:
        if pattern.match(message):
            return pattern.sub(replacement, message)
    return message
