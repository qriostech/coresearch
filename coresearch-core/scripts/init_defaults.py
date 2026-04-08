import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.project import create_project
from core.seed import create_seed
from core.branch import create_branch

project = create_project("default", user_id=1)
print(f"Project created: id={project.id}, root={project.project_root}")

seed = create_seed(project.id, "blackgolem", "https://github.com/example/blackgolem.git")
print(f"Seed created:    id={seed.id}, uuid={seed.uuid}, url={seed.repository_url}")

branch = create_branch(seed.id, "main")
print(f"Branch created:  id={branch.id}, uuid={branch.uuid}, commit={branch.commit}")
