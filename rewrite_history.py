import os
import subprocess
import random
import datetime
import shutil
import time


script_name = os.path.basename(__file__)
project_directory = "."
repo_path = os.path.abspath(project_directory)
git_dir = os.path.join(repo_path, ".git")
backup_dir_name = "WEditor_final_state_backup"
backup_dir = os.path.abspath(os.path.join(repo_path, "..", backup_dir_name))


contributors = [
    {"name": "Marsel Fayzullin", "email": "saddog.sec@gmail.com"},
    {"name": "Vsevolod Nazamudinov", "email": "seva.nazmudinov@gmail.com"},
    {"name": "Yashin Dmitry", "email": "d.yashin@innopolis.university"},
    {"name": "Igor Kuzmenkov", "email": "tkdomigor@gmail.com"},
]
authors_by_email = {a["email"]: a for a in contributors}

min_commits_per_person = 3


start_date = datetime.datetime(2025, 4, 22, 0, 0, 0)
end_date = datetime.datetime(2025, 4, 26, 23, 59, 59)
time_delta = end_date - start_date
total_seconds = int(time_delta.total_seconds())
commit_stages = [
    {
        "message": "Initial commit",
        "files": [".gitignore", "LICENSE"],
        "author_email": "tkdomigor@gmail.com",
    },
    {
        "message": "requirements",
        "files": ["requirements.txt"],
        "author_email": "d.yashin@innopolis.university",
    },
    {
        "message": "CRDT WIP",
        "files": ["crdt/rga.py"],
        "author_email": "tkdomigor@gmail.com",
    },
    {
        "message": "CRDT redis",
        "files": ["common/broker.py"],
        "author_email": "tkdomigor@gmail.com",
    },
    {
        "message": "flask back",
        "files": ["server/main.py"],
        "author_email": "d.yashin@innopolis.university",
    },
    {
        "message": "client index",
        "files": ["client/templates/index.html"],
        "author_email": "saddog.sec@gmail.com",
    },
    {
        "message": "js",
        "files": ["client/static/script.js"],
        "author_email": "seva.nazmudinov@gmail.com",
    },
    {
        "message": "css",
        "files": ["client/static/style.css"],
        "author_email": "saddog.sec@gmail.com",
    },
    {
        "message": "Integrate CRDT logic with server",
        "files": ["server/main.py", "crdt/rga.py"],
        "author_email": "tkdomigor@gmail.com",
    },
    {
        "message": "Set up WebSocket comms framework",
        "files": ["server/main.py", "client/static/script.js", "requirements.txt"],
        "author_email": "d.yashin@innopolis.university",
    },
    {
        "message": "Implement client op sending",
        "files": ["client/static/script.js"],
        "author_email": "seva.nazmudinov@gmail.com",
    },
    {
        "message": "dockerize",
        "files": ["Dockerfile", "docker-compose.yml"],
        "author_email": "d.yashin@innopolis.university",
    },
    {
        "message": "README and PDF report",
        "files": ["README.md"],
        "author_email": "seva.nazmudinov@gmail.com",
    },
]

num_commits = len(commit_stages)


def run_command(command, working_dir, check=True, env=None):
    try:
        cmd_env = os.environ.copy()
        if env:
            cmd_env.update(env)

        print(f"Running: {' '.join(command)} in {working_dir}")
        if env:
            print(f"  with extra env: {env}")

        result = subprocess.run(
            command,
            cwd=working_dir,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=cmd_env
        )
        if result.stdout:
            print("Stdout:", result.stdout.strip())
        if result.stderr:
            print("Stderr:", result.stderr.strip())
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(command)}")
        print(f"Return code: {e.returncode}")
        if e.stdout:
            print(f"Stdout:\n{e.stdout.strip()}")
        if e.stderr:
            print(f"Stderr:\n{e.stderr.strip()}")
        raise
    except Exception as e:
        print(f"Unexpected error running command {' '.join(command)}: {e}")
        raise


def clean_working_directory(path, keep_files):
    print(f"Cleaning working directory: {path}")
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        if item not in keep_files:
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                print(f"  Removed: {item}")
            except Exception as e:
                print(f"  Error removing {item_path}: {e}")


def copy_stage_files(stage_files, source_root, dest_root):
    print(f"Copying stage files to {dest_root}:")
    for rel_path in stage_files:
        source_path = os.path.join(source_root, rel_path)
        dest_path = os.path.join(dest_root, rel_path)

        if not os.path.exists(source_path):
            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            print(
                f"  Info: Source file/dir not found in backup (may be new/modified): {source_path}"
            )
            continue

        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        try:
            if os.path.isdir(source_path):
                shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                print(f"  Copied dir: {rel_path}")
            else:
                shutil.copy2(source_path, dest_path)
                print(f"  Copied file: {rel_path}")
        except Exception as e:
            print(f"  Error copying {rel_path}: {e}")


def generate_commit_plan(stages, authors_dict, all_authors_list, min_per_author):
    num_stages = len(stages)
    author_commit_counts = {email: 0 for email in authors_dict.keys()}
    assigned_authors_email = [None] * num_stages
    unassigned_stage_indices = list(range(num_stages))

    print("\nAssigning specified authors...")
    for i, stage in enumerate(stages):
        if "author_email" in stage:
            email = stage["author_email"]
            if email in authors_dict:
                assigned_authors_email[i] = email
                author_commit_counts[email] += 1
                unassigned_stage_indices.remove(i)
                print(f"  Stage {i + 1} ('{stage['message']}') assigned to: {email}")
            else:
                print(
                    f"  Warning: Specified author email '{email}' for stage {i + 1} not found in contributors."
                )

    print("\nAssigning authors to meet minimums...")
    authors_needing_commits = []
    for email, count in author_commit_counts.items():
        needed = min_per_author - count
        if needed > 0:
            authors_needing_commits.extend([email] * needed)

    random.shuffle(authors_needing_commits)
    random.shuffle(unassigned_stage_indices)

    num_to_assign = min(len(authors_needing_commits), len(unassigned_stage_indices))
    for i in range(num_to_assign):
        stage_idx = unassigned_stage_indices[i]
        email = authors_needing_commits[i]
        assigned_authors_email[stage_idx] = email
        author_commit_counts[email] += 1
        stage_message = stages[stage_idx]["message"]
        print(
            f"  Stage {stage_idx + 1} ('{stage_message}') assigned to {email} (to meet minimum)"
        )

    unassigned_stage_indices = unassigned_stage_indices[num_to_assign:]

    print("\nAssigning remaining stages randomly...")
    if unassigned_stage_indices:
        author_emails_list = [a["email"] for a in all_authors_list]
        for stage_idx in unassigned_stage_indices:
            random_email = random.choice(author_emails_list)
            assigned_authors_email[stage_idx] = random_email
            author_commit_counts[random_email] += 1
            stage_message = stages[stage_idx]["message"]
            print(
                f"  Stage {stage_idx + 1} ('{stage_message}') assigned randomly to {random_email}"
            )

    print("\nGenerating and sorting timestamps...")
    timestamps = []
    for _ in range(num_stages):
        rand_seconds = random.randint(0, total_seconds)
        timestamps.append(start_date + datetime.timedelta(seconds=rand_seconds))
    timestamps.sort()

    final_plan = []
    tz_offset = datetime.timezone(datetime.timedelta(hours=3))

    for i in range(num_stages):
        stage = stages[i]
        assigned_email = assigned_authors_email[i]
        if not assigned_email or assigned_email not in authors_dict:
            print(
                f"Error: Could not assign a valid author for stage {i + 1}. Skipping stage."
            )
            continue

        author_info = authors_dict[assigned_email]
        commit_time = timestamps[i]
        commit_time_aware = commit_time.replace(tzinfo=tz_offset)
        timestamp_iso = commit_time_aware.isoformat()

        final_plan.append(
            {
                "message": stage["message"],
                "files": stage["files"],
                "author": f"{author_info['name']} <{author_info['email']}>",
                "date": timestamp_iso,
                "author_email": assigned_email,
            }
        )

    print("\n--- Final Commit Plan --- ")
    final_counts = {email: 0 for email in authors_dict.keys()}
    for commit in final_plan:
        print(
            f"  Date: {commit['date']}, Author: {commit['author']}, Message: {commit['message']}"
        )
        final_counts[commit["author_email"]] += 1
    print("-------------------------")
    print("Final Author commit counts:", final_counts)
    if any(count < min_per_author for count in final_counts.values()):
        print(f"Warning: Not all authors reached the minimum {min_per_author} commits.")
    print("-------------------------")

    return final_plan


if __name__ == "__main__":
    print("--- Starting Git History Rewrite ---")
    print(f"This script will operate on the project in: {repo_path}")
    print(f"It needs the *final* project state to exist here to create the history.")
    print(f"A backup of the current state will be temporarily created at: {backup_dir}")
    print("The existing '.git' directory (if any) will be DELETED.")
    print("-" * 30)
    confirmation = input("Are you sure you want to continue? (yes/no): ")

    if confirmation.lower() != "yes":
        print("Operation cancelled.")
        exit()

    print(f"\nBacking up current state to {backup_dir}...")
    if os.path.exists(backup_dir):
        print("  Removing existing backup directory...")
        shutil.rmtree(backup_dir)
    try:
        ignore_patterns = shutil.ignore_patterns(".git", script_name, backup_dir_name)
        shutil.copytree(
            repo_path, backup_dir, ignore=ignore_patterns, dirs_exist_ok=True
        )
        print("  Backup complete.")
    except Exception as e:
        print(f"Error during backup: {e}")
        print("Aborting script.")
        exit()

    if os.path.exists(git_dir):
        print(f"\nRemoving existing Git directory: {git_dir}")
        try:
            if os.name == "nt":
                subprocess.run(
                    f'rmdir /s /q "{git_dir}"',
                    shell=True,
                    check=True,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
            else:
                run_command(["rm", "-rf", git_dir], repo_path)
        except Exception as e:
            print(
                f"Error removing .git directory: {e}. Please remove it manually and retry."
            )
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
            exit()

    print("\nInitializing new Git repository...")
    run_command(["git", "init"], repo_path)
    run_command(["git", "branch", "-M", "dev"], repo_path)

    clean_working_directory(repo_path, [".git", script_name])

    commit_plan = generate_commit_plan(
        commit_stages, authors_by_email, contributors, min_commits_per_person
    )

    print("\nExecuting commit plan...")
    for i, commit in enumerate(commit_plan):
        print(
            f"\n--- Creating commit {i + 1}/{len(commit_plan)}: {commit['message']} ---"
        )

        copy_stage_files(commit["files"], backup_dir, repo_path)

        run_command(["git", "add", "."], repo_path)

        status_result = run_command(["git", "status", "--porcelain"], repo_path)
        if not status_result.stdout.strip() and i > 0:
            print(
                "  No changes detected to commit for this stage, skipping commit (but preserving timestamp)."
            )
            continue

        commit_env = {
            "GIT_AUTHOR_DATE": commit["date"],
            "GIT_COMMITTER_DATE": commit["date"]
        }

        commit_cmd = [
            "git",
            "commit",
            "-m",
            commit["message"],
            f"--author={commit['author']}",
        ]
        run_command(commit_cmd, repo_path, env=commit_env)
        time.sleep(0.1)

    print("\nCleaning up backup directory...")
    if os.path.exists(backup_dir):
        try:
            shutil.rmtree(backup_dir)
            print(f"  Removed: {backup_dir}")
        except Exception as e:
            print(f"  Error removing backup directory {backup_dir}: {e}")
            print("  Please remove it manually.")

    print("\n--- Script finished ---")
    print("New Git history created.")
    print("Verify the history using 'git log --pretty=fuller'.")
