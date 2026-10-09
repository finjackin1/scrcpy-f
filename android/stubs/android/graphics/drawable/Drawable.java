package android.graphics.drawable;

import android.graphics.Canvas;

public abstract class Drawable {
    public int getIntrinsicWidth() { return 0; }
    public int getIntrinsicHeight() { return 0; }
    public void setBounds(int a, int b, int c, int d) {}
    public abstract void draw(Canvas c);
}