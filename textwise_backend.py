import os
import time
import requests
import openai
import sqlite3
import datetime
from langdetect import detect
import nltk
from flask import Flask, jsonify
from flask_cors import CORS
import threading
import logging

# === Configuration ===

# Set up logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing

# Fetch API keys from environment variables (recommended for security)
# Fetch API keys from environment variables (recommended for security)
OPENAI_API_KEY="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"
TEXTBEE_API_KEY="4a3647f0-6828-4732-942e-328ee2754ae3"
TEXTBEE_DEVICE_ID="671e6d1b7536f1499245e69f"

# Ensure that all API keys are provided
if not OPENAI_API_KEY or not TEXTBEE_API_KEY or not TEXTBEE_DEVICE_ID:
    logging.error("Error: Missing API keys. Please set OPENAI_API_KEY, TEXTBEE_API_KEY, and TEXTBEE_DEVICE_ID environment variables.")
    exit(1)

# Set the OpenAI API key
openai.api_key = OPENAI_API_KEY

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
        logging.error(f"Error fetching received SMS: {e}")
        return []

@app.route('/api/get_conversations')
def get_conversations():
    conn_api = sqlite3.connect('conversation_history.db', check_same_thread=False)
    cursor_api = conn_api.cursor()

    # Fetch messages from the last 24 hours
    cursor_api.execute('''
        SELECT sender_number, role, content, timestamp
        FROM conversations
        WHERE timestamp >= datetime('now', '-1 day')
        ORDER BY timestamp DESC
    ''')
    conversations = cursor_api.fetchall()
    conn_api.close()

    data = []
    for sender_number, role, content, timestamp in conversations:
        data.append({
            'phone_number': sender_number,
            'role': role,
            'content': content,
            'timestamp': timestamp
        })
    return jsonify(data)

def reset_database():
    # Function to reset the database by deleting old messages
    conn_reset = sqlite3.connect('conversation_history.db', check_same_thread=False)
    cursor_reset = conn_reset.cursor()
    # Delete messages older than 1 day
    cursor_reset.execute("DELETE FROM conversations WHERE timestamp < datetime('now', '-1 day')")
    conn_reset.commit()
    conn_reset.close()
    logging.info("Database reset: Old messages deleted.")

# Call reset_database() at startup to clear old messages
reset_database()

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
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        lesson_content = response.choices[0].message.content.strip()
        return lesson_content
    except Exception as e:
        logging.error(f"Error generating lesson content with OpenAI: {e}")
        return "Sorry, I'm unable to generate the lesson content at the moment."

def process_message_with_openai(sender_number, message_text, understanding_level, cursor, conn):
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
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )
        assistant_reply = response.choices[0].message.content.strip()

        # Messages are saved in the main loop now, so we can comment these out
        # cursor.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
        #                (sender_number, 'user', message_text))
        # cursor.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
        #                (sender_number, 'assistant', assistant_reply))
        # conn.commit()

        return assistant_reply
    except Exception as e:
        logging.error(f"Error processing message with OpenAI: {e}")
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
            logging.info(f"Sent SMS to {recipient_number}: {sms}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error sending SMS to {recipient_number}: {e}")

def send_and_save_sms(recipient_number, message_text, cursor, conn):
    send_sms(recipient_number, message_text)
    # Save the assistant's message to the database
    cursor.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
                   (recipient_number, 'assistant', message_text))
    conn.commit()

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

# === Flask Routes ===

@app.route('/api/get_user_data')
def get_user_data():
    conn_api = sqlite3.connect('conversation_history.db', check_same_thread=False)
    cursor_api = conn_api.cursor()

    cursor_api.execute('''
        SELECT sender_number, content, timestamp
        FROM conversations
        WHERE timestamp IN (
            SELECT MAX(timestamp)
            FROM conversations
            GROUP BY sender_number
        )
    ''')
    conversations = cursor_api.fetchall()
    data = []
    for sender_number, content, timestamp in conversations:
        data.append({
            'phone_number': sender_number,
            'last_message': content,
            'timestamp': timestamp
        })

    conn_api.close()
    return jsonify(data)

# === Main Execution Loop ===

def main():
    logging.info("Starting TextWise Backend Service...")
    conn_main = sqlite3.connect('conversation_history.db', check_same_thread=False)
    cursor_main = conn_main.cursor()

    # Create the users table if it doesn't exist
    cursor_main.execute('''
    CREATE TABLE IF NOT EXISTS users (
        sender_number TEXT PRIMARY KEY,
        understanding_level INTEGER,
        state TEXT,
        topic TEXT
    )
    ''')
    conn_main.commit()

    # Create the conversations table if it doesn't exist
    cursor_main.execute('''
    CREATE TABLE IF NOT EXISTS conversations (
        sender_number TEXT,
        role TEXT,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn_main.commit()

    last_processed_timestamp = load_last_processed_timestamp()

    while True:
        messages = get_received_sms()

        if not messages:
            time.sleep(2)
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
            logging.info(f"Received SMS from {sender_number}: {message_text}")

            # Save the user message to the database
            cursor_main.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
                                (sender_number, 'user', message_text))
            conn_main.commit()

            cursor_main.execute('SELECT understanding_level, state, topic FROM users WHERE sender_number = ?', (sender_number,))
            user_data = cursor_main.fetchone()

            if user_data is None:
                # New user, send initial greeting
                prompt = (
                    "👋 Hello! Welcome to TextWise, your personalized learning companion.\n"
                    "I'm here to help you learn something new today.\n"
                    "What would you like to explore? 📚✨"
                )
                send_and_save_sms(sender_number, prompt, cursor_main, conn_main)
                cursor_main.execute('INSERT INTO users (sender_number, understanding_level, state, topic) VALUES (?, ?, ?, ?)', (sender_number, None, 'awaiting_topic', None))
                conn_main.commit()
            else:
                understanding_level, state, topic = user_data
                if message_text.lower() in ['hi', 'hello', 'hey']:
                    # Reset the user's state and understanding level
                    cursor_main.execute('UPDATE users SET state = ?, understanding_level = ?, topic = ? WHERE sender_number = ?', ('awaiting_topic', None, None, sender_number))
                    conn_main.commit()
                    # Send the initial greeting
                    prompt = (
                        "👋 Hello! Welcome back to TextWise!\n"
                        "What would you like to explore today? 📚✨"
                    )
                    send_and_save_sms(sender_number, prompt, cursor_main, conn_main)
                elif state == 'awaiting_topic':
                    # User should provide a topic
                    topic = message_text
                    cursor_main.execute('UPDATE users SET state = ?, topic = ? WHERE sender_number = ?', ('awaiting_level', topic, sender_number))
                    conn_main.commit()
                    prompt = (
                        f"Great choice! To tailor the lessons on {topic} to your needs, please share your current understanding level.\n"
                        "Reply with a number between 1 (Beginner) and 5 (Expert). 🔢"
                    )
                    send_and_save_sms(sender_number, prompt, cursor_main, conn_main)
                elif state == 'awaiting_level':
                    try:
                        level = int(message_text)
                        if 1 <= level <= 5:
                            cursor_main.execute('UPDATE users SET understanding_level = ?, state = ? WHERE sender_number = ?', (level, 'ready', sender_number))
                            conn_main.commit()
                            reply = (
                                f"🌟 Awesome! We'll tailor the content to your Level {level} understanding.\n"
                                "Ready for your first lesson? Reply with \"Yes\" to begin or \"More Info\" for details. 📖✨"
                            )
                            send_and_save_sms(sender_number, reply, cursor_main, conn_main)
                        else:
                            send_and_save_sms(sender_number, "Please enter a number between 1 and 5. 🔢", cursor_main, conn_main)
                    except ValueError:
                        send_and_save_sms(sender_number, "Please enter a valid number between 1 and 5. 🔢", cursor_main, conn_main)
                elif state == 'ready':
                    if message_text.lower() in ['yes', 'y']:
                        cursor_main.execute('UPDATE users SET state = ? WHERE sender_number = ?', ('in_lesson', sender_number))
                        conn_main.commit()
                        # Start the lesson
                        lesson_content = generate_lesson_content(topic, understanding_level)
                        lesson_message = f"🚀 Great! Here's your first lesson on {topic}:\n{lesson_content}\nFeel free to ask questions or reply with \"Next\" to continue. 💡📘"
                        send_and_save_sms(sender_number, lesson_message, cursor_main, conn_main)
                    elif message_text.lower() == 'more info':
                        info = (
                            "💡 TextWise delivers educational content directly to your phone via SMS, making learning accessible anytime, anywhere!\n"
                            "You can receive lessons, ask questions, and track your progress—all through simple text messages. 📱🌍\n"
                            "Ready to begin your learning journey? Reply with \"Yes\" to start or \"Help\" for more options. 📘✨"
                        )
                        send_and_save_sms(sender_number, info, cursor_main, conn_main)
                    else:
                        send_and_save_sms(sender_number, "Please reply with \"Yes\" to start your lesson or \"More Info\" if you need assistance. 😊🔄", cursor_main, conn_main)
                elif state == 'in_lesson':
                    if message_text.lower() == 'next':
                        # Proceed to next lesson
                        next_lesson_content = generate_lesson_content(topic, understanding_level)
                        next_lesson_message = f"👏 Well done! Here's your next lesson on {topic}:\n{next_lesson_content}\nRemember, you can always ask questions or type \"Menu\" for options. 📚✨"
                        send_and_save_sms(sender_number, next_lesson_message, cursor_main, conn_main)
                    elif message_text.lower() == 'menu':
                        menu = "📖 Menu Options:\n- Next: Proceed to the next lesson\n- Repeat: Repeat the last lesson\n- Help: Get assistance\n- Exit: End the session"
                        send_and_save_sms(sender_number, menu, cursor_main, conn_main)
                    elif message_text.lower() == 'exit':
                        send_and_save_sms(sender_number, "👋 Goodbye! If you ever want to continue your learning journey, just text us anytime. Have a fantastic day! 🌟😊", cursor_main, conn_main)
                        cursor_main.execute('UPDATE users SET state = ? WHERE sender_number = ?', ('completed', sender_number))
                        conn_main.commit()
                    else:
                        # Handle user questions
                        reply_text = process_message_with_openai(sender_number, message_text, understanding_level, cursor_main, conn_main)
                        send_sms(sender_number, reply_text)
                        # Save the assistant's message to the database
                        cursor_main.execute('INSERT INTO conversations (sender_number, role, content) VALUES (?, ?, ?)',
                                           (sender_number, 'assistant', reply_text))
                        conn_main.commit()
                else:
                    # If the state is 'completed' or any other, reset the conversation
                    cursor_main.execute('UPDATE users SET state = ?, understanding_level = ?, topic = ? WHERE sender_number = ?', ('awaiting_topic', None, None, sender_number))
                    conn_main.commit()
                    send_and_save_sms(sender_number, "Welcome back! What would you like to learn today? 📚✨", cursor_main, conn_main)

            # Update the last processed timestamp
            save_last_processed_timestamp(message_timestamp)
            last_processed_timestamp = message_timestamp

        time.sleep(2)

    conn_main.close()

if __name__ == "__main__":
    threading.Thread(target=main).start()
    app.run(host='0.0.0.0', port=5001)
