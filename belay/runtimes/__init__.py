from belay.runtimes import anchored, naive, replay_content, replay_position

RUNTIMES = {
    naive.NAME: naive,
    replay_position.NAME: replay_position,
    replay_content.NAME: replay_content,
    anchored.NAME: anchored,
}

# Order used in every table and chart, weakest to strongest.
ORDER = [naive.NAME, replay_position.NAME, replay_content.NAME, anchored.NAME]

__all__ = ["RUNTIMES", "ORDER"]
