import customtkinter as ctk
import requests
import json
import threading
from datetime import datetime
import re

# 1. Use better_profanity for bad language detection
try:
    from better_profanity import profanity
except ImportError:
    raise ImportError("Please install better_profanity library: pip install better-profanity")

# Initialize/censor words
profanity.load_censor_words()

# 2. Manually curated college data (no "professors" entry)
COLLEGE_INFO = {
    "about": (
        "St. Xavier's College, Mumbai, is a leading institution offering a wide range of "
        "undergraduate and postgraduate courses in Arts, Science, Commerce, and Management. "
        "Known for its rich legacy and distinguished alumni, the college emphasizes "
        "holistic student development."
    ),
    "courses": [
        "Bachelor of Arts (B.A.)",
        "Bachelor of Science (B.Sc.)",
        "Bachelor of Commerce (B.Com.)",
        "Bachelor of Management Studies (BMS)",
        "Bachelor of Mass Media (BMM)",
        "M.A. in Public Policy",
        "M.Sc. in Biotechnology",
        "PhD Programs in select disciplines"
    ],
    "placement_cell": {
        "head": "Ms.Radhika Tendulkar",
        "email": "radhika.tendulkar@xaviers.edu",
        "highest_package_ever": 24,  # in LPA
        "latest_info": (
            "The 2023 placement season saw record participation from 55 companies, "
            "with an average package of 8 LPA."
        )
    }
}

SYSTEM_PROMPT = f"""
You are JoSi, the official placement and academic guide chatbot for St. Xavier's College, Mumbai. 
Use the following knowledge to answer queries precisely:

**College Data**:
About: {COLLEGE_INFO["about"]}
Available Courses: {', '.join(COLLEGE_INFO["courses"])}

**Placement Cell**:
Head: {COLLEGE_INFO["placement_cell"]["head"]}
Email: {COLLEGE_INFO["placement_cell"]["email"]}
Highest Package Ever: {COLLEGE_INFO["placement_cell"]["highest_package_ever"]} LPA
Latest Info: {COLLEGE_INFO["placement_cell"]["latest_info"]}

You can provide:
 - Placement guidance
 - Interview prep
 - Course suggestions
 - Info about the college’s history or academic programs

**Important**:
1. If a user’s text has profanity or offensive language, politely refuse to answer further.
2. For the "Placement Test," ask 5 technical + 5 behavioral questions one-by-one. 
   Collect each answer, then evaluate all at the end.
3. Use short paragraphs and **Markdown** formatting (headings `###`, bullets, bold, etc.).
4. Highest package is exactly 24 LPA, be precise if asked.

NOTE: If you are returning data for a "company check," respond EXACTLY with "VALID" or "INVALID" and nothing else.
"""

# 3. API Configuration
API_KEY = "AIzaSyC4v9u3RoGa_A1VuXT3xQSfl_XBRwGCP48"  # <-- Replace with your real API key
API_URL = "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent"

def call_gemini_api(prompt):
    """
    Makes a POST request to Gemini with the given prompt.
    Returns the text response or an error message if any.
    """
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    url = f"{API_URL}?key={API_KEY}"
    try:
        resp = requests.post(url, headers=headers, json=data)
        if resp.status_code == 200:
            # Typical structure from Gemini
            return resp.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"Error {resp.status_code}: {resp.text}"
    except Exception as e:
        return f"Error: {str(e)}"

def contains_profanity(text):
    return profanity.contains_profanity(text)

def gemini_check_company(company_name):
    """
    Checks if the given company_name is recognized by Gemini in the context
    of campus placements at St. Xavier's College.
    
    If the model acknowledges the company, it MUST respond exactly with "VALID".
    If the company is not recognized, it MUST respond exactly with "INVALID".
    
    We parse strictly: if the final text is "valid", we return True. Otherwise False.
    """
    check_prompt = f"""
Check if the company name "{company_name}" is recognized in the context
of campus placements at St. Xavier's College, Mumbai.

If yes, respond EXACTLY with "VALID".
Otherwise respond EXACTLY with "INVALID".

IMPORTANT: No extra text or explanation.
"""
    
    response = call_gemini_api(check_prompt)
    print("DEBUG – Company check raw response:", repr(response))  # Debug print
    
    # We'll parse strictly:
    if response.strip().lower() == "valid":
        return True
    return False

def gemini_generate_questions(role):
    """
    Dynamically generate exactly 5 technical and 5 behavioral interview questions
    relevant to the given 'role'.
    If role is IT/software related, we want at least 1-2 coding questions.
    
    We prompt Gemini to return pure JSON with exactly two keys:
      "technical_questions": [...],
      "behavioral_questions": [...]
    """
    prompt = f"""
Generate exactly 5 technical interview questions and 5 behavioral interview questions
for the role: "{role}" at St. Xavier's College campus placements.
- If the role is IT/software related, include at least 2 coding or programming questions.
Return ONLY valid JSON, with keys:
  "technical_questions": <array of 5 strings>,
  "behavioral_questions": <array of 5 strings>.
No code fences, no extra commentary.
"""
    raw_response = call_gemini_api(prompt)
    print("DEBUG – Generate questions raw response:", repr(raw_response))  # Debug print
    
    # We'll try to extract the portion from the first '{' to the last '}' as naive JSON capture.
    start_idx = raw_response.find('{')
    end_idx = raw_response.rfind('}')
    json_str = ""
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = raw_response[start_idx:end_idx+1].strip()
    
    # Attempt parse
    try:
        data = json.loads(json_str)
        tech = data["technical_questions"]
        beh = data["behavioral_questions"]
        # Basic validations:
        if len(tech) != 5 or len(beh) != 5:
            raise ValueError("Did not receive exactly 5 technical and 5 behavioral questions.")
    except Exception as e:
        print("DEBUG – JSON parse error or mismatch:", e)
        print("DEBUG – Falling back to default questions.")
        tech = [
            "Explain what OOP is.",
            "What is a database index?",
            "How does a binary search work?",
            "What is an API, and how do you use it?",
            "Describe how you would optimize a slow SQL query."
        ]
        beh = [
            "Tell me about a challenge you overcame in a team.",
            "How do you handle tight deadlines?",
            "Describe a time you received critical feedback.",
            "What does work-life balance mean to you?",
            "What motivates you to succeed?"
        ]
    return tech, beh


# 5. Test Manager (One-by-one Q&A)
class TestManager:
    def __init__(self):
        self.in_test = False
        self.question_index = 0
        self.test_data = {
            'company': '',
            'role': '',
            'technical_questions': [],
            'behavioral_questions': [],
            'user_answers': []
        }

    def set_company(self, name):
        """
        Call gemini_check_company. If it's valid, store it; otherwise return False.
        """
        return gemini_check_company(name)

    def set_role(self, role):
        self.test_data['role'] = role

    def generate_test_questions(self):
        """
        Dynamically fetch Qs from Gemini or fallback.
        """
        tech, beh = gemini_generate_questions(self.test_data['role'])
        self.test_data['technical_questions'] = tech
        self.test_data['behavioral_questions'] = beh

    def next_question(self):
        total_tech = len(self.test_data['technical_questions'])
        total_beh = len(self.test_data['behavioral_questions'])

        if self.question_index < total_tech:
            q = self.test_data['technical_questions'][self.question_index]
        elif self.question_index < total_tech + total_beh:
            q = self.test_data['behavioral_questions'][self.question_index - total_tech]
        else:
            q = None

        if q:
            self.question_index += 1
        return q

    def store_answer(self, answer):
        self.test_data['user_answers'].append(answer)

    def all_answers_collected(self):
        needed = len(self.test_data['technical_questions']) + len(self.test_data['behavioral_questions'])
        return len(self.test_data['user_answers']) >= needed

    def evaluate_answers(self):
        """
        Evaluate the user's answers with Gemini. 
        Provide feedback + a final (0-100%) 'placement probability'.
        """
        prompt = f"""
Evaluate these interview answers for {self.test_data['company']} ({self.test_data['role']}):
Technical Questions:
{self.test_data['technical_questions']}
Behavioral Questions:
{self.test_data['behavioral_questions']}
Answers:
{self.test_data['user_answers']}

Give detailed feedback for each answer and a final (0-100%) 'placement probability'.
"""
        result = call_gemini_api(prompt)
        return result


# 6. Base Chatbot GUI
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "primary": "#2563eb",
    "secondary": "#1e40af",
    "background": "#1e1e2e",
    "surface": "#313244",
    "text": "#cdd6f4",
    "accent": "#89b4fa",
    "error": "#f87171",
    "success": "#34d399"
}

class ChatbotGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("JoSi - St. Xavier's College Mumbai Guide")
        self.geometry("400x600")  # More phone-friendly
        self.configure(fg_color=COLORS["background"])

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        self.create_header()
        self.create_chat_container()
        self.create_input_area()

        self.is_processing = False
        self.setup_tags()

        # Welcome text with disclaimers
        welcome_text = (
            "### Welcome to JoSi! 👋\n\n"
            "I’m your **placement & academic guide** at St. Xavier’s College, Mumbai.\n"
            "Ask about courses, highest package info, or the placement cell.\n"
            "I can assist with interview prep, career guidance, and more.\n\n"
            "**Disclaimer**: I'm an AI-generated chatbot. Information provided is for **reference only**.\n"
            "For official details, please contact the college placement cell.\n\n"
            "How can I help you today?"
        )
        self.add_message("JoSi", welcome_text)

    def create_header(self):
        self.header_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["surface"], corner_radius=10)
        self.header_frame.grid(row=0, column=0, padx=5, pady=(0, 5), sticky="ew")

        self.header_label = ctk.CTkLabel(
            self.header_frame,
            text="JoSi - St. Xavier's College",
            text_color=COLORS["accent"],
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.header_label.grid(row=0, column=0, padx=10, pady=10)

    def create_chat_container(self):
        self.chat_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["surface"], corner_radius=10)
        self.chat_frame.grid(row=1, column=0, padx=5, pady=(0, 5), sticky="nsew")
        self.chat_frame.grid_rowconfigure(0, weight=1)
        self.chat_frame.grid_columnconfigure(0, weight=1)

        self.chat_display = ctk.CTkTextbox(
            self.chat_frame,
            corner_radius=0,
            fg_color="transparent",
            font=("Helvetica", 12),
            wrap="word"
        )
        self.chat_display.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.chat_display.configure(state="disabled")

    def create_input_area(self):
        self.input_frame = ctk.CTkFrame(self.main_frame, fg_color=COLORS["surface"], corner_radius=10)
        self.input_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.input_field = ctk.CTkTextbox(
            self.input_frame,
            height=50,
            corner_radius=10,
            font=("Helvetica", 12),
            wrap="word"
        )
        self.input_field.grid(row=0, column=0, padx=(5, 5), pady=5, sticky="ew")
        self.input_field.bind("<Return>", self.handle_return)

        self.send_button = ctk.CTkButton(
            self.input_frame,
            text="Send",
            width=70,
            command=self.send_message,
            corner_radius=10,
            font=("Helvetica", 12, "bold"),
            fg_color=COLORS["primary"],
            hover_color=COLORS["secondary"]
        )
        self.send_button.grid(row=0, column=1, padx=(0, 5), pady=5)

    def setup_tags(self):
        self.chat_display.configure(state="normal")
        self.chat_display.tag_config("timestamp", foreground=COLORS["accent"])
        self.chat_display.tag_config("user", foreground=COLORS["primary"])
        self.chat_display.tag_config("bot", foreground=COLORS["success"])
        self.chat_display.tag_config("message", foreground=COLORS["text"])
        self.chat_display.tag_config("error", foreground=COLORS["error"])
        self.chat_display.tag_config("bold", foreground=COLORS["accent"])
        self.chat_display.tag_config("heading", foreground=COLORS["success"])
        self.chat_display.tag_config("bullet", foreground=COLORS["accent"])
        self.chat_display.tag_config("code", foreground=COLORS["accent"], background=COLORS["surface"])
        self.chat_display.configure(state="disabled")

    def format_markdown(self, text):
        """
        Simple parser for headings (###), bold (**...**),
        and bullet lines (starting with '•').
        """
        lines = text.split('\n')
        leftover = ""

        for line in lines:
            # Headings
            if line.startswith('###'):
                heading_text = line.strip('#').strip()
                self.chat_display.insert("end", heading_text + "\n", "heading")
                continue

            # Bullets
            if line.strip().startswith('•'):
                self.chat_display.insert("end", "  ", "message")
                self.chat_display.insert("end", "• ", "bullet")
                bullet_text = line.strip('• ').strip()
                self.chat_display.insert("end", bullet_text + "\n", "message")
                continue

            # Look for bold or code in the line
            while '**' in line or '`' in line:
                bold_match = re.search(r'\*\*(.*?)\*\*', line)
                if bold_match:
                    start, end = bold_match.span()
                    leftover += line[:start]
                    self.chat_display.insert("end", leftover, "message")
                    self.chat_display.insert("end", bold_match.group(1), "bold")
                    line = line[end:]
                    leftover = ""
                    continue

                code_match = re.search(r'`(.*?)`', line)
                if code_match:
                    start, end = code_match.span()
                    leftover += line[:start]
                    self.chat_display.insert("end", leftover, "message")
                    self.chat_display.insert("end", code_match.group(1), "code")
                    line = line[end:]
                    leftover = ""
                    continue

            leftover += line + "\n"
            self.chat_display.insert("end", leftover, "message")
            leftover = ""

    def add_message(self, sender, message, is_error=False):
        self.chat_display.configure(state="normal")
        timestamp = datetime.now().strftime("%H:%M")
        self.chat_display.insert("end", f"[{timestamp}] ", "timestamp")

        if sender == "You":
            self.chat_display.insert("end", f"{sender}: ", "user")
        else:
            self.chat_display.insert("end", f"{sender}: ", "bot")

        self.chat_display.insert("end", "\n")

        if is_error:
            self.chat_display.insert("end", message + "\n\n", "error")
        else:
            self.format_markdown(message + "\n\n")

        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def handle_return(self, event):
        # If user hits Enter without SHIFT, we treat it as "Send"
        if not event.state & 0x1:
            self.send_message()
            return "break"
        return None

    def send_message(self):
        if self.is_processing:
            return

        user_text = self.input_field.get("1.0", "end-1c").strip()
        if not user_text:
            return

        self.input_field.delete("1.0", "end")
        self.add_message("You", user_text)

        self.is_processing = True
        self.input_field.configure(state="disabled")
        self.send_button.configure(state="disabled")

        thread = threading.Thread(target=self.process_message, args=(user_text,))
        thread.start()

    def process_message(self, user_text):
        """
        Default behavior: just show a placeholder response.
        The real responses happen in EnhancedChatbotGUI.
        """
        try:
            response = "Base ChatbotGUI: no external call here."
            is_error = False
        except Exception as e:
            response = f"Error: {str(e)}"
            is_error = True

        self.after(0, self.add_message, "JoSi", response, is_error)
        self.after(0, self.enable_input)

    def enable_input(self):
        self.is_processing = False
        self.input_field.configure(state="normal")
        self.send_button.configure(state="normal")
        self.input_field.focus()


# 7. Enhanced Chatbot with Test + Real Model
class EnhancedChatbotGUI(ChatbotGUI):
    def __init__(self):
        super().__init__()
        self.conversation_history = []
        self.test_manager = TestManager()
        self.add_test_controls()

    def add_test_controls(self):
        """
        Two buttons: Start the Placement Test or Exit Test mode.
        """
        self.test_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.test_frame.grid(row=3, column=0, padx=5, pady=5, sticky="ew")
        
        self.start_test_btn = ctk.CTkButton(
            self.test_frame,
            text="Start Placement Test",
            command=self.start_test
        )
        self.start_test_btn.pack(side='left', padx=5)
        
        self.exit_test_btn = ctk.CTkButton(
            self.test_frame,
            text="Exit Test",
            command=self.exit_test,
            state='disabled'
        )
        self.exit_test_btn.pack(side='left', padx=5)

    def start_test(self):
        self.test_manager.in_test = True
        self.add_message("JoSi", 
            "Starting placement test!\n"
            "Please enter a **company name** you believe visits St. Xavier's College for placements:"
        )
        self.exit_test_btn.configure(state='normal')
        self.start_test_btn.configure(state='disabled')

    def exit_test(self):
        self.test_manager = TestManager()
        self.exit_test_btn.configure(state='disabled')
        self.start_test_btn.configure(state='normal')
        self.add_message("JoSi", "Exited test mode. How else can I help you?")

    def handle_test_flow(self, user_input):
        """
        Walk through company check -> role -> ask questions -> final evaluation.
        """
        tm = self.test_manager

        # Step 1: If no company chosen yet, check the company:
        if not tm.test_data['company']:
            valid = tm.set_company(user_input)
            if not valid:
                self.add_message(
                    "JoSi", 
                    "That company is **NOT recognized** for campus placements (or the model isn't sure). "
                    "Please try another company name."
                )
                return
            # If recognized:
            tm.test_data['company'] = user_input
            self.add_message("JoSi", f"Great! Now enter the role you're applying for at {user_input}:")

        # Step 2: If we have the company but no role set:
        elif not tm.test_data['role']:
            tm.set_role(user_input)
            tm.generate_test_questions()
            self.add_message("JoSi", "Excellent! Let's begin with the first question:")
            self.ask_next_question()

        # Step 3: If both company and role are set, store the user's answer:
        else:
            tm.store_answer(user_input)
            if tm.all_answers_collected():
                # All 10 answers collected, do final evaluation
                result = tm.evaluate_answers()
                self.add_message("JoSi", result)
                self.exit_test()
            else:
                self.ask_next_question()

    def ask_next_question(self):
        question = self.test_manager.next_question()
        if question is None:
            # If no more questions left, do final evaluation
            result = self.test_manager.evaluate_answers()
            self.add_message("JoSi", result)
            self.exit_test()
        else:
            self.add_message("JoSi", f"**Q{self.test_manager.question_index}:** {question}")

    def get_response(self, prompt):
        """
        Send the user's prompt + short conversation context to Gemini.
        """
        # If user text has profanity, block:
        if contains_profanity(prompt):
            return "I'm sorry, but I cannot respond to that."

        # Build a short conversation context
        last_msgs = "\n".join([
            f"{msg['sender']}: {msg['text']}"
            for msg in self.conversation_history[-5:]
        ])
        final_text = f"{SYSTEM_PROMPT}\n\n{last_msgs}\nUser: {prompt}"
        
        response = call_gemini_api(final_text)
        print("DEBUG – Normal chat raw response:", repr(response))  # Debug print
        return response

    def send_message(self):
        """
        Overridden to handle normal conversation or test mode.
        """
        if self.is_processing:
            return

        user_text = self.input_field.get("1.0", "end-1c").strip()
        if not user_text:
            return

        self.input_field.delete("1.0", "end")
        self.add_message("You", user_text)

        # Check profanity quickly
        if contains_profanity(user_text):
            self.add_message("JoSi", "Sorry, I can't respond to that language.", True)
            self.enable_input()
            return

        # Append user text to conversation
        self.conversation_history.append({'sender': 'user', 'text': user_text})

        self.is_processing = True
        self.input_field.configure(state="disabled")
        self.send_button.configure(state="disabled")

        if self.test_manager.in_test:
            # If we are in test mode, handle test flow
            thread = threading.Thread(target=self.process_test_message, args=(user_text,))
        else:
            # Otherwise do normal conversation
            thread = threading.Thread(target=self.process_normal_message, args=(user_text,))
        thread.start()

    def process_test_message(self, user_text):
        try:
            self.handle_test_flow(user_text)
        except Exception as e:
            self.after(0, self.add_message, "JoSi", f"Error in test flow: {str(e)}", True)
        finally:
            self.after(0, self.enable_input)

    def process_normal_message(self, user_text):
        """
        Get normal chat response from Gemini and display it.
        """
        try:
            resp = self.get_response(user_text)
            is_error = resp.startswith("Error")
            self.conversation_history.append({'sender': 'JoSi', 'text': resp})
            self.after(0, self.add_message, "JoSi", resp, is_error)
        except Exception as e:
            self.after(0, self.add_message, "JoSi", f"Error: {str(e)}", True)
        finally:
            self.after(0, self.enable_input)


# 8. MAIN
if __name__ == "__main__":
    app = EnhancedChatbotGUI()
    app.mainloop()
