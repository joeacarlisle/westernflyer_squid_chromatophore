"""Follow an ROI box through a video so it stays on the animal while the camera and the animals move.

The box is moved with the median motion of feature points inside it (pyramidal Lucas-Kanade optical flow,
checked by tracking each point backwards as well).  Only translation is followed: the box keeps its size.
Brightness changes from flashing are the signal, so the points are found and followed on a contrast-equalised,
blurred copy of the frame; the brightness itself is always read from the untouched frame.
"""
import cv2
import numpy as np

_CLAHE = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))


def prepare(gray_u8):
    """Frame used for finding and following points (not for measuring brightness)."""
    return cv2.GaussianBlur(_CLAHE.apply(gray_u8), (3, 3), 0)


class BoxTracker:
    def __init__(self, box, cfg):
        self.x, self.y, self.w, self.h = [float(v) for v in box]
        self.cfg = cfg
        self.prev = None
        self.pts = np.empty((0, 1, 2), np.float32)
        self.lost = False

    def _detect(self, img):
        x0, y0 = int(round(self.x)), int(round(self.y))
        mask = np.zeros(img.shape[:2], np.uint8)
        mask[y0:y0 + int(self.h), x0:x0 + int(self.w)] = 255
        p = cv2.goodFeaturesToTrack(img, maxCorners=int(self.cfg['max_corners']), qualityLevel=0.005, minDistance=3,
                                    blockSize=5, mask=mask)
        return p if p is not None else np.empty((0, 1, 2), np.float32)

    def _inside(self, pts, margin=2.0):
        px, py = pts[:, 0, 0], pts[:, 0, 1]
        return (px >= self.x - margin) & (px <= self.x + self.w + margin) & (py >= self.y - margin) & (py <= self.y + self.h + margin)

    def update(self, gray_u8):
        """Feed the next frame; returns (x, y, w, h, lost) of the box on that frame."""
        img = prepare(gray_u8)
        H, W = img.shape[:2]
        if self.prev is None:
            self.pts = self._detect(img)
        else:
            moved = False
            if len(self.pts):
                win = (int(self.cfg['win_px']),) * 2
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(self.prev, img, self.pts, None, winSize=win, maxLevel=2)
                back, st2, _ = cv2.calcOpticalFlowPyrLK(img, self.prev, nxt, None, winSize=win, maxLevel=2)
                err = np.abs(back - self.pts).reshape(-1, 2).max(axis=1)
                good = (st.ravel() == 1) & (st2.ravel() == 1) & (err < float(self.cfg['fb_error_px']))
                if good.sum() >= int(self.cfg['min_points']):
                    d = np.median((nxt[good] - self.pts[good]).reshape(-1, 2), axis=0)
                    self.x = float(np.clip(self.x + d[0], 0, W - self.w))
                    self.y = float(np.clip(self.y + d[1], 0, H - self.h))
                    self.pts = nxt[good]
                    self.pts = self.pts[self._inside(self.pts)]
                    moved = True
            if len(self.pts) < int(self.cfg['redetect_below']):
                new = self._detect(img)
                self.pts = np.concatenate([self.pts, new]) if len(self.pts) else new
            self.lost = not moved
        self.prev = img
        return self.x, self.y, self.w, self.h, self.lost
