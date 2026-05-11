from src.db_sql import SQLDatabase


class Teacher:
    def __init__(self, user="daniel"):
        self.user = user
        self.sql = SQLDatabase()

    def answer_question(self, question: str):
        ...

    def generate_lesson_plan(self, topic: str, context: str = ""):
        ... 

    def lesson(self, prompt: str):
        ...


if __name__ == "__main__":
    Teacher().answer_question("How is inductance derived from spin?")