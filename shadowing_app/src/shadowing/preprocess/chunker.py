from __future__ import annotations


class ClauseChunker:
    """
    把课文拆成句 / 分句块。
    推荐一个 chunk 2~6 秒，方便 seek 与局部重生成。
    """

    def split_text(self, text: str) -> list[str]:
        # TODO: 按中文标点与长度做分句
        # 可加入最大字数、最短块长度、语义停顿规则
        raise NotImplementedError