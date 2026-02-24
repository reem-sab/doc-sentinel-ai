import os
import re
from google import genai

class DocSentinelIntelligence:
    def __init__(self, file_path):
        self.file_path = file_path
        self.api_key = os.getenv("GOOGLE_API_KEY")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            self.content = f.read()
        
        if self.api_key:
            # The new SDK client setup
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

    def calculate_score(self):
        """Calculates a basic AI-readability score."""
        score = 100
        # Check for vague pronouns at start of lines
        pronouns = len(re.findall(r'(?m)^(\s*)(It|This|They|Those)\s', self.content))
        score -= min(pronouns * 10, 40)
        
        # Check for basic Markdown structure
        if not re.search(r'^## ', self.content, re.M):
            score -= 20
            
        return max(score, 0)

    def get_ai_suggestions(self):
        """Uses Gemini 2.0 to generate professional writing suggestions."""
        if not self.client:
            return "⚠️ GOOGLE_API_KEY not found. Skipping AI analysis."

        prompt = f"Act as a Senior Technical Writer. Review this for 'AI-readability': {self.content}"
        
        try:
            # We are using 2.0-flash here to avoid the 404 versioning bugs
            response = self.client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"❌ Connection Error: {str(e)}"

if __name__ == "__main__":
    target = 'getting-started.md' 
    if os.path.exists(target):
        sentinel = DocSentinelIntelligence(target)
        print(f"📊 AI-Readability Score: {sentinel.calculate_score()}%")
        print("\n🤖 Gemini's Suggestions:")
        print(sentinel.get_ai_suggestions())
    else:
        print(f"❌ Could not find {target}")