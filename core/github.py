# vless_scanner/core/github.py
import os
import asyncio
import logging
from github import Github
from github.GithubException import GithubException, UnknownObjectException

class ServiceError(Exception):
    pass

class GithubUploader:
    def __init__(self, config: dict, stats):
        self.config = config
        self.stats = stats

    async def upload(self, content: str):
        if not self.config.get('enabled'):
            return
        
        logging.info(f"Attempting to update file in GitHub repo: {self.config['owner']}/{self.config['repo']}")
        try:
            token = self.config.get('github_token') or os.environ.get('GITHUB_TOKEN')
            await asyncio.to_thread(
                self._sync_update,
                token,
                f"{self.config['owner']}/{self.config['repo']}",
                self.config['file_path'],
                content if not self.config.get('upload_base64') else content,
                self.config['commit_message']
            )
            self.stats.increment('github_upload_success')
        except Exception as e:
            self.stats.increment('github_upload_failed')
            raise ServiceError("GitHub repository upload failed") from e

    def _sync_update(self, token: str, repo_name: str, file_path: str, content: str, message: str):
        """Synchronous function to create or update a file in a GitHub repository."""
        try:
            g = Github(token)
            repo = g.get_repo(repo_name)
            
            try:
                # Get the existing file to get its SHA, which is required for an update
                file_contents = repo.get_contents(file_path)
                repo.update_file(
                    path=file_path,
                    message=message,
                    content=content,
                    sha=file_contents.sha
                )
                logging.info(f"Successfully updated file '{file_path}' in repo '{repo_name}'.")
            except UnknownObjectException:
                # If the file doesn't exist, create it
                repo.create_file(
                    path=file_path,
                    message=message,
                    content=content
                )
                logging.info(f"Successfully created new file '{file_path}' in repo '{repo_name}'.")

        except GithubException as e:
            error_message = getattr(e, 'data', {}) .get('message', str(e)) if hasattr(e, 'data') else str(e)
            raise ServiceError(f"GitHub API error: {error_message}") from e
        except Exception as e:
            raise ServiceError(f"An unexpected error occurred during GitHub upload: {e}") from e
