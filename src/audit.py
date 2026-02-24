import os
import re
from google import genai

class DocSentinelIntelligence:
    def __init__(self, file_path):
        self.file_path = file_path
        self.api_key = os.getenv("GOOGLE_API_KEY")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            self.content = f.read()
        
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def calculate_score(self):
        """Calculates a basic AI-readability score."""
        score = 100
        # Penalty for vague pronouns (Context Drift)
        pronouns = len(re.findall(r'(?m)^(\s*)(It|This|They|Those)\s', self.content))
        score -= min(pronouns * 10, 40)
        
        # Penalty for lack of structure
        if not re.search(r'^## ', self.content, re.M):
            score -= 20
            
        return max(score, 0)

    def get_ai_suggestions(self):
        """Uses Gemini to generate professional writing suggestions."""
        if not self.client:
            return ["⚠️ GOOGLE_API_KEY not found. Skipping AI analysis."]

        prompt = f"""
        Act as a Senior Technical Writer and AI Specialist. 
        Review the following documentation for 'AI-readability' (suitability for LLMs and RAG).
        Provide 3 specific, actionable suggestions to improve it.
        
        Documentation Content:
        ---
        {self.content}
        ---
        """
        
        try:
            response = self.client.models.generate_content(
                model="gemini-1.5-flash", 
                contents=prompt
            )
            return response.text
        except Exception as e:
            return [f"❌ Error calling Gemini: {str(e)}"]

if __name__ == "__main__":
    # Point this to whatever doc you want to test
    target = 'getting-started.md' 
    if os.path.exists(target):
        sentinel = DocSentinelIntelligence(target)
        score = sentinel.calculate_score()
        suggestions = sentinel.get_ai_suggestions()

        print(f"📊 AI-Readability Score: {score}%")
        print("\n🤖 Gemini's Suggestions:")
        print(suggestions)