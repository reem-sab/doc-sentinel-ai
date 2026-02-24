import os
from github import Github, Auth
from google import genai  # Note the change here
from dotenv import load_dotenv

load_dotenv()

# 1. Setup GitHub
auth = Auth.Token(os.getenv("GITHUB_TOKEN"))
g = Github(auth=auth)
REPO_NAME = "reem-sab/doc-sentinel-ai" 

# 2. Setup Google Gemini Client
# This uses the new SDK that Google is moving everyone toward
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

def get_real_docs():
    repo = g.get_repo(REPO_NAME)
    file_content = repo.get_contents("getting-started.md")
    return file_content.decoded_content.decode()

def run_audit(diff, docs):
    prompt = f"""
    You are a Senior Technical Writer. 
    Code Change (Diff): {diff}
    Existing Documentation: {docs}
    
    Task: Does the code change make the documentation outdated? 
    If yes, provide a concise updated version of the documentation in Markdown.
    If no, say "Documentation is up to date."
    """
    
    # Using the 'gemini-1.5-flash' model with the new client
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt
    )
    return response.text

# --- EXECUTION ---
try:
    print(f"Connecting to GitHub: {REPO_NAME}...")
    current_docs = get_real_docs()
    
    mock_diff = "+ def start_ai_audit(api_key, mode='strict'):"

    print("Available models:", [m.name for m in client.models.list()])
    
    print("Gemini 1.5 Flash is auditing...")
    result = run_audit(mock_diff, current_docs)
    
    print("\n--- AI AUDIT RESULT ---")
    print(result)

except Exception as e:
    print(f"Error: {e}")