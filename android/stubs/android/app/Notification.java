package android.app;

import android.graphics.drawable.Icon;
import android.os.Bundle;

public class Notification {
    public Action[] actions;
    public Bundle extras;
    public PendingIntent contentIntent;
    public Icon getLargeIcon() { return null; }
    public static class Action {
        public CharSequence title;
        public PendingIntent actionIntent;
        public RemoteInput[] getRemoteInputs() { return null; }
    }
}