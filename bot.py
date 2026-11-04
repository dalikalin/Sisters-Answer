# bot.py  (Option B: AI-powered answers)
# Steps for every question:
#   1. Find the 5 pieces of website text that best match the question
#   2. Send those pieces + the question to Claude
#   3. Send Claude's answer back on Telegram

import os      # to read secrets from the environment
import re      # to split text into words
import json    # to read site_data.json
import math    # for the maths that gives rare words more weight
from dotenv import load_dotenv                    # reads the .env file
from anthropic import AsyncAnthropic              # lets us talk to Claude
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load the secrets from the .env file
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")      # your Telegram token
# (the Claude key, ANTHROPIC_API_KEY, is picked up automatically below)

if not TELEGRAM_TOKEN:
    raise SystemExit("TELEGRAM_TOKEN is missing. Check your .env file.")

# Which Claude model to use. Haiku is the fastest and cheapest.
MODEL = "claude-haiku-5-5"

claude = AsyncAnthropic()   # the connection to Claude

# Instructions we give Claude with every question
# Instructions we give Claude with every question
SYSTEM_PROMPT = (
    "You are a helpful assistant for the Sisters of Code website. "
    "Answer the user's question using ONLY the website text provided. "
    "If the text does not contain the answer, reply only with: "
    "'Sorry, I could not find that on the Sisters of Code website.' "
    "Never mention 'the provided text' and never describe what the text contains. "
    "Do not guess or use outside knowledge. "
    "Write in plain text only: no asterisks, no markdown, no headings. "
    "For lists, start each line with a dash and a space. "
    "Keep answers short and clear. Reply in the same language as the question. "
    "The website text is split into numbered sources. On the very last line "
    "of your reply, write SOURCE: followed by the number of the main source "
    "you used (for example SOURCE: 2). If you could not find the answer, "
    "write SOURCE: none."
)

# Common words we ignore when searching, because they appear everywhere
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "at",
    "for", "and", "or", "what", "who", "how", "when", "where", "why", "do",
    "does", "you", "your", "i", "me", "my", "it", "this", "that", "with", "can",
}

# Word links: if the question has the word on the left, we also search for
# the words on the right. Add your own whenever the bot misses a question.
SYNONYMS = {
    "volunteer": "ambassador trainer partner involved",
    "located": "address campus toul kork",
    "location": "address campus toul kork",
    "contact": "address email",
}

def get_words(text):
    # Turn text into a set of lowercase words, without the common words
    words = re.findall(r"\w+", text.lower())
    words = [w for w in words if w not in STOP_WORDS]
    # Remove a plural "s" at the end, so "volunteers" matches "volunteer"
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words}

def load_chunks():
    # Read the website text and cut each page into pieces (chunks)
    with open("site_data.json", encoding="utf-8") as file:
        pages = json.load(file)

    chunks = []
    for page in pages:
        # Skip the homepage (all copies). It is only a menu of headings.
        if page["url"].rstrip("/").endswith("sistersofcode.org"):
            continue
        current = ""
        for line in page["text"].split("\n"):
            current += line + " "
            if len(current) > 800:          # a piece is long enough, save it
                chunks.append({"url": page["url"], "text": current.strip(), "words": get_words(current)})
                current = ""
        if current.strip():                 # save whatever is left over
            chunks.append({"url": page["url"], "text": current.strip(), "words": get_words(current)})
    return chunks

CHUNKS = load_chunks()   # load once when the bot starts

# Count how many chunks each word appears in
word_counts = {}
for chunk in CHUNKS:
    for word in chunk["words"]:
        word_counts[word] = word_counts.get(word, 0) + 1

# Give every word a weight: common words get near 0, rare words get a high weight
WEIGHTS = {word: math.log(len(CHUNKS) / count) for word, count in word_counts.items()}

def find_best_chunks(question, how_many=5):
    # Return the chunks that best match the question (highest score first)
    question_words = get_words(question)

    # Add the linked words from SYNONYMS
    for word in list(question_words):
        if word in SYNONYMS:
            question_words |= get_words(SYNONYMS[word])

    scored = []
    for chunk in CHUNKS:
        score = sum(WEIGHTS.get(word, 0) for word in question_words & chunk["words"])
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)   # best first
    return [chunk for score, chunk in scored[:how_many]]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Runs when someone sends /start
    await update.message.reply_text("Hi! Ask me a question about Sisters of Code.")

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Runs for every normal text message
    question = update.message.text
    best = find_best_chunks(question)

    # If nothing matched at all, don't spend money asking Claude
    if not best:
        await update.message.reply_text("Sorry, I couldn't find anything about that on the website.")
        return

    # Number each piece (Source 1, Source 2, ...) so Claude can tell us which one it used
    website_text = "\n\n".join(f"[Source {i}: {c['url']}]\n{c['text']}" for i, c in enumerate(best, start=1))

    try:
        # Ask Claude to answer using only that text
        response = await claude.messages.create(
            model=MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Website text:\n{website_text}\n\nQuestion: {question}",
            }],
        )
        # Claude's reply can have several blocks (some are "thinking").
        # We keep only the blocks that contain text, and join them together.
        reply = "".join(block.text for block in response.content if block.type == "text")
    except Exception as error:
        # If something goes wrong, show it in the terminal and tell the user
        print("Claude error:", error)
        await update.message.reply_text("Sorry, something went wrong. Please try again later.")
        return

    # Claude ends its reply with a line like "SOURCE: 2". We read that line,
    # remove it from the reply, and use the number to pick the right web address.
    match = re.search(r"SOURCE:\s*(\d+|none)\s*$", reply.strip(), re.IGNORECASE)
    if match:
        reply = reply.strip()[:match.start()].strip()
        choice = match.group(1)
        if choice.isdigit() and 1 <= int(choice) <= len(best):
            reply += "\n\nSource: " + best[int(choice) - 1]["url"]
    await update.message.reply_text(reply)

# Set up the bot and connect our functions to it
# (30 seconds of waiting time, because Telegram was slow before)
app = (
    Application.builder()
    .token(TELEGRAM_TOKEN)
    .connect_timeout(30)
    .read_timeout(30)
    .write_timeout(30)
    .pool_timeout(30)
    .get_updates_connect_timeout(30)
    .get_updates_read_timeout(30)
    .get_updates_write_timeout(30)
    .get_updates_pool_timeout(30)
    .build()
)
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))

print("Bot is running... (press Ctrl + C in the terminal to stop it)")
app.run_polling()