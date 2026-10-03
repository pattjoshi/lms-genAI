"""Fixed catalog: staff, courses, modules, topics, and the "story" users.

Students are generated randomly (with a fixed seed) in build.py; everything here is
hand-written so the data is realistic and stable. Phase 1 generates the course files
from the same topic list.
"""

# (full_name, email, city)
ADMIN = ("Neha Kapoor", "neha.kapoor@lmsdemo.in", "Bengaluru")
SUPPORT = [
    ("Rohan Das", "rohan.das@lmsdemo.in", "Kolkata"),
    ("Sneha Pillai", "sneha.pillai@lmsdemo.in", "Kochi"),
]

# Each course: code, title, description, price_inr, teacher, modules[(title, [(topic, difficulty)])]
COURSES = [
    {
        "code": "PY101",
        "title": "Python Programming",
        "description": "Python from zero: syntax, data structures, OOP and working with data.",
        "price_inr": 2999,
        "teacher": ("Vikram Singh", "vikram.singh@lmsdemo.in", "Jaipur"),
        "modules": [
            ("Python Basics", [("Variables and Data Types", "easy"), ("Control Flow", "easy"), ("Functions", "easy")]),
            (
                "Data Structures in Python",
                [("Lists and Tuples", "easy"), ("Dictionaries and Sets", "easy"), ("List Comprehensions", "medium")],
            ),
            (
                "Object-Oriented Python",
                [("Classes and Objects", "medium"), ("Inheritance", "medium"), ("Exceptions", "medium")],
            ),
            ("Working with Data", [("File Handling", "easy"), ("NumPy Basics", "medium"), ("Pandas Basics", "medium")]),
        ],
    },
    {
        "code": "ML201",
        "title": "Machine Learning Basics",
        "description": "The math and the core algorithms of classical machine learning.",
        "price_inr": 4999,
        "teacher": ("Meera Nair", "meera.nair@lmsdemo.in", "Thiruvananthapuram"),
        "modules": [
            (
                "Math Foundations",
                [("Linear Algebra Basics", "medium"), ("Derivatives", "medium"), ("Probability Basics", "medium")],
            ),
            (
                "Supervised Learning",
                [("Linear Regression", "medium"), ("Logistic Regression", "medium"), ("Gradient Descent", "medium")],
            ),
            (
                "Model Evaluation",
                [
                    ("Train Test Split", "easy"),
                    ("Overfitting and Regularization", "medium"),
                    ("Evaluation Metrics", "medium"),
                ],
            ),
            ("Unsupervised Learning", [("K-Means Clustering", "medium"), ("Principal Component Analysis", "hard")]),
        ],
    },
    {
        "code": "DL301",
        "title": "Deep Learning",
        "description": "Neural networks from the perceptron to CNNs and LSTMs.",
        "price_inr": 6999,
        "teacher": ("Suresh Rao", "suresh.rao@lmsdemo.in", "Hyderabad"),
        "modules": [
            (
                "Neural Network Basics",
                [("Perceptron", "medium"), ("Activation Functions", "medium"), ("Chain Rule", "medium")],
            ),
            (
                "Training Neural Networks",
                [("Backpropagation", "hard"), ("Loss Functions", "medium"), ("Optimizers", "hard")],
            ),
            (
                "Convolutional Neural Networks",
                [("Convolution", "hard"), ("Pooling", "medium"), ("CNN Architectures", "hard")],
            ),
            ("Sequence Models", [("Recurrent Neural Networks", "hard"), ("LSTM", "hard")]),
        ],
    },
    {
        "code": "NLP302",
        "title": "Natural Language Processing",
        "description": "From tokenization to transformers and retrieval-augmented generation.",
        "price_inr": 7499,
        "teacher": ("Kavita Joshi", "kavita.joshi@lmsdemo.in", "Pune"),
        "modules": [
            (
                "Text Processing",
                [
                    ("Tokenization", "easy"),
                    ("Stemming and Lemmatization", "easy"),
                    ("Bag of Words and TF-IDF", "medium"),
                ],
            ),
            ("Word Representations", [("Word Embeddings", "medium"), ("Word2Vec", "hard")]),
            ("Attention and Transformers", [("Attention Mechanism", "hard"), ("Transformers", "hard")]),
            ("Modern NLP", [("Pretrained Language Models", "hard"), ("Retrieval-Augmented Generation", "hard")]),
        ],
    },
    {
        "code": "DB201",
        "title": "Database Management Systems",
        "description": "Relational modelling, SQL from basics to joins, and transactions.",
        "price_inr": 3999,
        "teacher": ("Rahul Gupta", "rahul.gupta@lmsdemo.in", "Delhi"),
        "modules": [
            ("Relational Model", [("Tables and Keys", "easy"), ("ER Diagrams", "easy"), ("Normalization", "medium")]),
            (
                "SQL Basics",
                [("SELECT Queries", "easy"), ("Filtering and Sorting", "easy"), ("Aggregation and GROUP BY", "medium")],
            ),
            ("Advanced SQL", [("SQL Joins", "hard"), ("Subqueries", "hard"), ("Indexes", "medium")]),
            ("Transactions", [("ACID Properties", "medium"), ("Concurrency Control", "hard")]),
        ],
    },
    {
        "code": "DSA201",
        "title": "Data Structures and Algorithms",
        "description": "Complexity, core data structures, and classic algorithms.",
        "price_inr": 4499,
        "teacher": ("Priya Menon", "priya.menon@lmsdemo.in", "Chennai"),
        "modules": [
            ("Complexity Analysis", [("Big-O Notation", "medium"), ("Recursion", "medium")]),
            (
                "Linear Data Structures",
                [("Arrays", "easy"), ("Linked Lists", "medium"), ("Stacks and Queues", "medium")],
            ),
            (
                "Trees and Graphs",
                [
                    ("Binary Trees", "medium"),
                    ("Binary Search Trees", "medium"),
                    ("Graph Traversal BFS and DFS", "hard"),
                ],
            ),
            ("Algorithms", [("Sorting Algorithms", "medium"), ("Dynamic Programming", "hard")]),
        ],
    },
]

# Hand-picked students with a planted story (see data/seed_stories.md).
# Shown first on the login page so you know whom to log in as.
STORY_STUDENTS = {
    "riya": ("Riya Sharma", "riya.sharma@student.lmsdemo.in", "Lucknow", ["PY101", "ML201", "DL301"]),
    "ananya": ("Ananya Iyer", "ananya.iyer@student.lmsdemo.in", "Chennai", ["PY101", "ML201", "DL301", "NLP302"]),
    "arjun": ("Arjun Mehta", "arjun.mehta@student.lmsdemo.in", "Ahmedabad", ["DB201", "DSA201"]),
    "karan": ("Karan Verma", "karan.verma@student.lmsdemo.in", "Indore", ["PY101", "DB201"]),
}

STORY_USERS: dict[str, str] = {
    ADMIN[1]: "Admin: sees everything, AI cost dashboard",
    STORY_STUDENTS["riya"][1]: "Weak in Backpropagation and Chain Rule",
    STORY_STUDENTS["ananya"][1]: "Top performer across all her courses",
    STORY_STUDENTS["arjun"][1]: "Two failed payments for Deep Learning this month",
    STORY_STUDENTS["karan"][1]: "Locked out: 6 failed logins yesterday",
    SUPPORT[0][1]: "Support: will handle tickets (Phase 5)",
    COURSES[2]["teacher"][1]: "Teaches Deep Learning (Riya's weak course)",
    COURSES[4]["teacher"][1]: "Teaches DBMS: most students fail SQL Joins",
}
