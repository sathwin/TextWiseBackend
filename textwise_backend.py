import os
import time
import requests
import openai
import sqlite3
import datetime
from langdetect import detect
import nltk

# === Configuration ===

# Fetch API keys from environment variables (recommended for security)
OPENAI_API_KEY="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"
TEXTBEE_API_KEY="84d9cf32-3f8d-4237-a608-adab6363f7bf"
TEXTBEE_DEVICE_ID="671dc08e30206fdc681d8f13"
# Ensure that all API keys are provided
if not OPENAI_API_KEY or not TEXTBEE_API_KEY or not TEXTBEE_DEVICE_ID:
    print("Error: Missing API keys. Please set OPENAI_API_KEY, TEXTBEE_API_KEY, and TEXTBEE_DEVICE_ID environment variables.")
    exit(1)

# Set the OpenAI API key
openai.api_key = OPENAI_API_KEY

# Initialize the SQLite database
conn = sqlite3.connect('conversation_history.db', check_same_thread=False)
cursor = conn.cursor()

# Create the users table if it doesn't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    sender_number TEXT PRIMARY KEY,
    understanding_level INTEGER
)
''')
conn.commit()

# Check and add missing columns
cursor.execute("PRAGMA table_info(users);")
columns = [column[1] for column in cursor.fetchall()]

# Add 'state' column if it doesn't exist
if 'state' not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN state TEXT;")
    conn.commit()

# Add 'topic' column if it doesn't exist
if 'topic' not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN topic TEXT;")
    conn.commit()

# Create the conversations table if it doesn't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS conversations (
    sender_number TEXT,
    role TEXT,
    content TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')
conn.commit()

# Download necessary NLTK data
nltk.download('punkt', quiet=True)

# TextBee API endpoints
TEXTBEE_BASE_URL = 'https://api.textbee.dev/api/v1/gateway'
GET_RECEIVED_SMS_URL = f'{TEXTBEE_BASE_URL}/devices/{TEXTBEE_DEVICE_ID}/getReceivedSMS'
SEND_SMS_URL = f'{TEXTBEE_BASE_URL}/devices/{TEXTBEE_DEVICE_ID}/sendSMS'

# Path to store the last processed message timestamp
LAST_PROCESSED_TIMESTAMP_FILE = 'last_processed_timestamp.txt'

# === Functions ===

def get_received_sms():
    headers = {
        'x-api-key': TEXTBEE_API_KEY,
    }
    try:
        response = requests.get(GET_RECEIVED_SMS_URL, headers=headers)
        response.raise_for_status()
        messages = response.json().get('data', [])
        return messages
    except requests.exceptions.RequestException as e:
        print(f"Error fetching received SMS: {e}")
        return []

def generate_lesson_content(topic, understanding_level):
    """
    Generate lesson content using OpenAI API based on the topic and understanding level.
    """
    try:
        # Prepare the system message
        system_message = (
            "You are TextWise, an SMS-based learning platform that provides educational content to users "
            "in a friendly, interactive, and concise manner. Use appropriate emojis to make interactions engaging "
            "and maintain a conversational tone. Ensure all responses are concise to fit within SMS character limits "
            "(typically 160 characters). Tailor your responses based on user inputs and maintain context throughout the conversation."
        )

        # Adjust the assistant's behavior based on understanding level
        level_instructions = {
            1: "Provide explanations suitable for a beginner learner. Keep it simple and avoid jargon. 😊",
            2: "Explain concepts in a straightforward manner with basic terminology.",
            3: "Provide detailed explanations with examples.",
            4: "Offer in-depth insights and discuss advanced aspects of the topic.",
            5: "Provide comprehensive and technical explanations suitable for an expert. 🧠"
        }
        system_message += " " + level_instructions.get(understanding_level, "")

        # Prepare the user prompt
        lesson_prompt = f"Please provide a lesson on {topic}."

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": lesson_prompt}
        ]

        response = openai.ChatCompletion.create(
            model='gpt-4',
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        lesson_content = response.choices[0].message.content.strip()
        return lesson_content
    except Exception as e:
        print(f"Error generating lesson content with OpenAI: {e}")
        return "Sorry, I'm unable to generate the lesson content at the moment."

def process_message_with_openai(sender_number, message_text, understanding_level):
    try:
        language = detect(message_text)
    except:
        language = 'en'

    cursor.execute('SELECT role, content FROM conversations WHERE sender_number = ? ORDER BY timestamp', (sender_number,))
    history = [{'role': row[0], 'content': row[1]} for row in cursor.fetchall()]
    history.append({"role": "user", "content": message_text})

    system_message = (
        "You are TextWise, an SMS-based learning platform that provides educational content to users "
        "in a friendly, interactive, and concise manner. Your goal is to engage users, assess their "
        "understanding levels, and deliver personalized educational content via SMS. Use appropriate "
        "emojis to make interactions engaging and maintain a conversational tone. Ensure all responses "
        "are concise to fit within SMS character limits (typically 160 characters). Tailor your responses "
        "based on user inputs and maintain context throughout the conversation."
    )

    # Adjust the assistant's behavior based on understanding level
    level_instructions = {
        1: "Provide explanations suitable for a beginner learner. Keep it simple and avoid jargon. 😊",
        2: "Explain concepts in a straightforward manner with basic terminology.",
        3: "Provide detailed explanations with examples.",
        4: "Offer in-depth insights and discuss advanced aspects of the topic.",
        5: "Provide comprehensive and technical explanations suitable for an expert. 🧠"
    }
    system_message += " " + level_instructions.get(understanding_level, "")

    if language != 'en':
        system_message += f" Respond in {language}."

    messages = [{"role": "system", "content": system_message}] + history

    try:
        response = openai.ChatCompletion.create(
            model='gpt-4',
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )
        assistant_reply = response.choices[0].message.content.strip()

        cursor.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
                       (sender_number, 'user', message_text))
        cursor.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
                       (sender_number, 'assistant', assistant_reply))
        conn.commit()

        return assistant_reply
    except Exception as e:
        print(f"Error processing message with OpenAI: {e}")
        return "Sorry, I'm unable to process your request at the moment."

def split_message_into_sms(message_text):
    max_total_length = 600
    max_sms_length = 160
    message_text = message_text[:max_total_length]
    sentences = nltk.tokenize.sent_tokenize(message_text)

    sms_messages = []
    current_sms = ''
    for sentence in sentences:
        if len(current_sms) + len(sentence) + 1 > max_sms_length:
            sms_messages.append(current_sms.strip())
            current_sms = sentence + ' '
        else:
            current_sms += sentence + ' '
    if current_sms:
        sms_messages.append(current_sms.strip())

    if len(sms_messages) > 1:
        total_parts = len(sms_messages)
        sms_messages = [f"({i+1}/{total_parts}) {sms}" for i, sms in enumerate(sms_messages)]
    return sms_messages

def send_sms(recipient_number, message_text):
    sms_messages = split_message_into_sms(message_text)
    headers = {
        'x-api-key': TEXTBEE_API_KEY,
        'Content-Type': 'application/json',
    }
    for sms in sms_messages:
        data = {
            'recipients': [recipient_number],
            'message': sms,
        }
        try:
            response = requests.post(SEND_SMS_URL, headers=headers, json=data)
            response.raise_for_status()
            print(f"Sent SMS to {recipient_number}: {sms}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending SMS to {recipient_number}: {e}")

def load_last_processed_timestamp():
    if os.path.exists(LAST_PROCESSED_TIMESTAMP_FILE):
        with open(LAST_PROCESSED_TIMESTAMP_FILE, 'r') as file:
            return file.read().strip()
    else:
        current_time = (datetime.datetime.utcnow() - datetime.timedelta(seconds=5)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        return current_time

def save_last_processed_timestamp(timestamp):
    with open(LAST_PROCESSED_TIMESTAMP_FILE, 'w') as file:
        file.write(timestamp)

# === Main Execution Loop ===

def main():
    print("Starting TextWise Backend Service...")
    last_processed_timestamp = load_last_processed_timestamp()

    while True:
        messages = get_received_sms()

        if not messages:
            time.sleep(5)
            continue

        last_timestamp_dt = datetime.datetime.strptime(last_processed_timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')

        new_messages = []
        for message in messages:
            message_timestamp = message.get('receivedAt')
            message_timestamp_dt = datetime.datetime.strptime(message_timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
            if message_timestamp_dt > last_timestamp_dt:
                new_messages.append(message)

        new_messages.sort(key=lambda x: x.get('receivedAt', ''))

        for message in new_messages:
            message_timestamp = message.get('receivedAt')
            sender_number = message.get('sender')
            message_text = message.get('message').strip()
            print(f"Received SMS from {sender_number}: {message_text}")

            cursor.execute('SELECT understanding_level, state, topic FROM users WHERE sender_number = ?', (sender_number,))
            user_data = cursor.fetchone()

            if user_data is None:
                # New user, send initial greeting
                prompt = (
                    "👋 Hello! Welcome to TextWise, your personalized learning companion.\n"
                    "I'm here to help you learn something new today.\n"
                    "What would you like to explore? 📚✨"
                )
                send_sms(sender_number, prompt)
                cursor.execute('INSERT INTO users (sender_number, understanding_level, state, topic) VALUES (?, ?, ?, ?)', (sender_number, None, 'awaiting_topic', None))
                conn.commit()
            else:
                understanding_level, state, topic = user_data
                if message_text.lower() in ['hi', 'hello', 'hey']:
                    # Reset the user's state and understanding level
                    cursor.execute('UPDATE users SET state = ?, understanding_level = ?, topic = ? WHERE sender_number = ?', ('awaiting_topic', None, None, sender_number))
                    conn.commit()
                    # Send the initial greeting
                    prompt = (
                        "👋 Hello! Welcome back to TextWise!\n"
                        "What would you like to explore today? 📚✨"
                    )
                    send_sms(sender_number, prompt)
                elif state == 'awaiting_topic':
                    # User should provide a topic
                    topic = message_text
                    cursor.execute('UPDATE users SET state = ?, topic = ? WHERE sender_number = ?', ('awaiting_level', topic, sender_number))
                    conn.commit()
                    prompt = (
                        f"Great choice! To tailor the lessons on {topic} to your needs, please share your current understanding level.\n"
                        "Reply with a number between 1 (Beginner) and 5 (Expert). 🔢"
                    )
                    send_sms(sender_number, prompt)
                elif state == 'awaiting_level':
                    try:
                        level = int(message_text)
                        if 1 <= level <= 5:
                            cursor.execute('UPDATE users SET understanding_level = ?, state = ? WHERE sender_number = ?', (level, 'ready', sender_number))
                            conn.commit()
                            reply = (
                                f"🌟 Awesome! We'll tailor the content to your Level {level} understanding.\n"
                                "Ready for your first lesson? Reply with \"Yes\" to begin or \"More Info\" for details. 📖✨"
                            )
                            send_sms(sender_number, reply)
                        else:
                            send_sms(sender_number, "Please enter a number between 1 and 5. 🔢")
                    except ValueError:
                        send_sms(sender_number, "Please enter a valid number between 1 and 5. 🔢")
                elif state == 'ready':
                    if message_text.lower() in ['yes', 'y']:
                        cursor.execute('UPDATE users SET state = ? WHERE sender_number = ?', ('in_lesson', sender_number))
                        conn.commit()
                        # Start the lesson
                        lesson_content = generate_lesson_content(topic, understanding_level)
                        lesson_message = f"🚀 Great! Here's your first lesson on {topic}:\n{lesson_content}\nFeel free to ask questions or reply with \"Next\" to continue. 💡📘"
                        send_sms(sender_number, lesson_message)
                    elif message_text.lower() == 'more info':
                        info = (
                            "💡 TextWise delivers educational content directly to your phone via SMS, making learning accessible anytime, anywhere!\n"
                            "You can receive lessons, ask questions, and track your progress—all through simple text messages. 📱🌍\n"
                            "Ready to begin your learning journey? Reply with \"Yes\" to start or \"Help\" for more options. 📘✨"
                        )
                        send_sms(sender_number, info)
                    else:
                        send_sms(sender_number, "Please reply with \"Yes\" to start your lesson or \"More Info\" if you need assistance. 😊🔄")
                elif state == 'in_lesson':
                    if message_text.lower() == 'next':
                        # Proceed to next lesson
                        next_lesson_content = generate_lesson_content(topic, understanding_level)
                        next_lesson_message = f"👏 Well done! Here's your next lesson on {topic}:\n{next_lesson_content}\nRemember, you can always ask questions or type \"Menu\" for options. 📚✨"
                        send_sms(sender_number, next_lesson_message)
                    elif message_text.lower() == 'menu':
                        menu = "📖 Menu Options:\n- Next: Proceed to the next lesson\n- Repeat: Repeat the last lesson\n- Help: Get assistance\n- Exit: End the session"
                        send_sms(sender_number, menu)
                    elif message_text.lower() == 'exit':
                        send_sms(sender_number, "👋 Goodbye! If you ever want to continue your learning journey, just text us anytime. Have a fantastic day! 🌟😊")
                        cursor.execute('UPDATE users SET state = ? WHERE sender_number = ?', ('completed', sender_number))
                        conn.commit()
                    else:
                        # Handle user questions
                        reply_text = process_message_with_openai(sender_number, message_text, understanding_level)
                        send_sms(sender_number, reply_text)
                else:
                    # If the state is 'completed' or any other, reset the conversation
                    cursor.execute('UPDATE users SET state = ?, understanding_level = ?, topic = ? WHERE sender_number = ?', ('awaiting_topic', None, None, sender_number))
                    conn.commit()
                    send_sms(sender_number, "Welcome back! What would you like to learn today? 📚✨")

            # Update the last processed timestamp
            save_last_processed_timestamp(message_timestamp)
            last_processed_timestamp = message_timestamp

        time.sleep(2)

if __name__ == "__main__":
    main()
