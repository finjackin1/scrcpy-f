package android.service.notification;

public abstract class NotificationListenerService {
    public void onListenerConnected() {}
    public void onNotificationPosted(StatusBarNotification sbn) {}
    public void onNotificationRemoved(StatusBarNotification sbn) {}
    public StatusBarNotification[] getActiveNotifications() { return null; }
}