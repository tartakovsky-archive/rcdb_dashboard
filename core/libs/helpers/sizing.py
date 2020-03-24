class SizingAlgo:
    def size(self, proba: float) -> float:
        pass


class PercentSizing(SizingAlgo):
    def __init__(self, percent: float, threshold: float = 0.5, direction: str = 'both'):
        supported_directions = ['pos', 'neg', 'both']
        if direction not in supported_directions:
            raise ValueError(
                f'{direction} direction is not supported. Should be one of the following: {supported_directions}'
            )

        self.percent = percent
        self.threshold = threshold
        self.direction = direction

    def size(self, proba: float) -> float:
        if self.direction == 'pos':
            return self.percent if proba > self.threshold else 0
        elif self.direction == 'neg':
            return -self.percent if (1 - proba) > self.threshold else 0
        else:
            return self.percent if proba > self.threshold else -self.percent if (1 - proba) > self.threshold else 0


class KellySizing(SizingAlgo):
    def __init__(self, win_size: float, loss_size: float, divider: float = 1, direction: str = 'both'):
        supported_directions = ['pos', 'neg', 'both']
        if direction not in supported_directions:
            raise ValueError(
                f'{direction} direction is not supported. Should be one of the following: {supported_directions}'
            )

        self.win_size = win_size
        self.loss_size = loss_size
        self.divider = divider
        self.direction = direction

    def size(self, proba: float) -> float:
        def kelly_fn(win: float, loss: float, p: float) -> float:
            return p / abs(loss) - (1 - p) / win

        pos_kelly = kelly_fn(self.win_size, self.loss_size, proba)
        neg_kelly = -kelly_fn(self.win_size, self.loss_size, 1 - proba)

        if self.direction == 'pos':
            kelly = pos_kelly if pos_kelly > 0 else 0
        elif self.direction == 'neg':
            kelly = neg_kelly if neg_kelly < 0 else 0
        else:
            kelly = pos_kelly if pos_kelly > 0 else neg_kelly if neg_kelly < 0 else 0

        return kelly / self.divider