from src.db_sql import SQLDatabase


class Teacher:
    def __init__(self, user="daniel"):
        self.sql = SQLDatabase()
        self.user_profile = self.get_user_profile(user)

    def get_user_profile(self, user: str):
        # Fetch user profile from the database
        query = f"SELECT * FROM users WHERE username = '{user}'"
        result = self.sql.execute(query)
        if result:
            return result[0]  # Assuming the first result is the user profile
        else:
            raise ValueError(f"User '{user}' not found in the database.")

    def answer_question(self, question: str):
        ...

    def generate_lesson_plan(self, topic: str, context: str = ""):
        ... 

    def lesson(self, prompt: str):
        ...


if __name__ == "__main__":
    Teacher().answer_question("How is inductance derived from spin?")