import asyncio
import threading
import time
from datetime import datetime

import speech_recognition as sr
from openai import OpenAI

from ai.clients.ai_client_factory import AiClientFactory
from ai.rag.functions_rag_system import RagSystem
from src.processing.text_to_speech import TextToSpeech
from src.processing.voice_to_text import voice_to_text
from src.processing.voice_to_text_faster import voice_to_text_faster
from src.processing.voice_to_text_mlx import voice_to_text_mlx
from src.search.search import AudioChatConfig

vtt_type = "MLX"  # MLX, FASTER_WHISPER, WHISPER
language_map = {
    "german": "de",
    "english": "en"
}
user_language = "german"
config = AudioChatConfig().get_config()
open_ai_server = config["API_ENDPOINTS"]["OPENAI"]
llm_api_key = config["API_KEYS"]["OPENAI"]
llm_model = config["API_MODELS"]["OPENAI"]
whisper_model_type = "small"

chat_bot_name = "elsa"
chat_duration_until_pause = 10

# blacklist of words that are wrongly recognized from speech to text but never spoken.
blacklist = ["Copyright", "WDR", "Thank you."]
now = datetime.now()
formatted_date = now.strftime("%A %d %B %Y")


def open_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as infile:
        return infile.read()


rag_system = RagSystem(config["STORAGE"]["RAG_VAULT_FILE"])
tts = TextToSpeech()
ai_client = AiClientFactory().create_ai_client(tts)

personalitySystemPrompt = open_file("ai/personalities/elsa.txt")
rag_function_system_message = rag_system.get_function_system_message("./ai/rag/functions_system_message.txt")
system_message = personalitySystemPrompt + f" Deine Hauptsprache ist {user_language} und du antwotest immer auf " \
                                   f"{user_language}. " \
                                   f"Das heutige Datum ist {formatted_date}.\n\n" + rag_function_system_message
chat_messages = [{"role": "system",
                  "content": system_message
                  }]

# -------------------------------------------------------------


openAiClient = OpenAI(api_key=llm_api_key, base_url=open_ai_server)

recognizer = sr.Recognizer()


def not_black_listed(spoken1):
    for item in blacklist:
        if spoken1.__contains__(item):
            print(f"Blacklisted item found: {item}")
            return False
    return True


chat_start_time = time.time()


async def main():
    thread = threading.Thread(target=tts.talking_worker)
    thread.daemon = True
    thread.start()
    global chat_start_time
    global chat_bot_name
    global chat_duration_until_pause
    with sr.Microphone() as source:
        while True:
            try:
                if vtt_type == "MLX":
                    spoken = voice_to_text_mlx(source, language_map[user_language], whisper_model_type)
                elif vtt_type == "FASTER_WHISPER":
                    spoken = voice_to_text_faster(source, language_map[user_language], whisper_model_type)
                else:
                    spoken = voice_to_text(source, language_map[user_language], whisper_model_type)
                spoken = spoken.strip()
                spoken_lower = spoken.lower()
                if spoken_lower.__contains__("hallo") and spoken_lower.__contains__(chat_bot_name):
                    chat_start_time = time.time()
                    print("Discussion resumed")
                if time.time() - chat_start_time > chat_duration_until_pause:
                    print("Discussion paused")
                    continue
                print(spoken_lower != "" and len(spoken_lower.split(" ")) > 3 and not_black_listed(spoken))
                if spoken != "" and len(spoken.split(" ")) > 3 and not_black_listed(spoken):
                    chat_start_time = time.time()
                    tts.stop_talking()
                    now_strftime = datetime.now().strftime('%H:%M:%S')
                    start_time = time.time()
                    print(now_strftime)
                    ask_llm = f"Die aktuelle Zeit ist {now_strftime}. {spoken}"
                    chat_messages.append({"role": "user", "content": ask_llm})
                    answer = ai_client.ask_ai_stream(chat_messages)
                    function_call = rag_system.parse_function_call(answer)
                    if function_call:
                        tts.add_to_queue(function_call["name"])
                        function_result = rag_system.execute_function_call(function_call)
                        print(f"Function result: {function_result}")
                        chat_messages.append({"role": "assistant", "content": function_result.strip()})
                    else:
                        chat_messages.append({"role": "assistant", "content": answer.strip()})
                    stop_time = time.time()
                    print("LLM duration: " + str(stop_time - start_time))

            except sr.UnknownValueError:
                print("Sorry, I could not understand what you said.")
            except sr.RequestError as e:
                print("Sorry, an error occurred while trying to access the Google Web Speech API: {0}".format(e))


asyncio.run(main())
