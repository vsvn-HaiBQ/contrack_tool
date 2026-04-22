from app.core.security import decrypt_secret
from app.modules.github.client import GitHubClient, GitHubClientError
from app.modules.github.service import build_pr_body, build_pr_title


class IntegrationConfigError(Exception):
    pass


def get_client(encrypted_token: str | None) -> GitHubClient:
    if not encrypted_token:
        raise IntegrationConfigError("GitHub token is not configured")
    token = decrypt_secret(encrypted_token)
    if not token:
        raise IntegrationConfigError("GitHub token is invalid")
    return GitHubClient(token)


def pull_request_template_resolved(repo: str, encrypted_token: str | None) -> str | None:
    return get_client(encrypted_token).get_pull_request_template(repo)


def branch_exists_resolved(repo: str, branch: str, encrypted_token: str | None) -> bool:
    return get_client(encrypted_token).branch_exists(repo, branch)


def create_pull_request_resolved(repo: str, *, title: str, body: str, base: str, head: str, encrypted_token: str | None) -> dict:
    return get_client(encrypted_token).create_pull_request(repo, title=title, body=body, base=base, head=head)


def test_connection(repo: str | None, encrypted_token: str | None) -> str:
    client = get_client(encrypted_token)
    user = client.get_current_user()
    if repo:
        repo_payload = client.get_repo(repo)
        return f"Connected as {user['login']} to {repo_payload['full_name']}"
    return f"Connected as {user['login']}"
