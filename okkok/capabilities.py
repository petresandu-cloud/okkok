# Copyright (C) 2026 Editerra AB. Okkok is a trademark of Editerra AB.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One table tying a capability to how each platform declares it and how compiled code reveals it.

A store asks two questions of every capability: is it declared, and is it
really used. Declaration comes from the manifest or Info.plist. Use comes from
the compiled code: Android class descriptors in the DEX string pool, iOS
frameworks in the executable's load commands and selectors in its strings.
A code shrinker renames the app's own classes and often the library classes
it bundles, but never the classes of the operating system, and rarely the
public method names the app calls on a library. So two signals are kept: class
descriptors, reliable for android.* and java.*, and plain API strings.
"""

CAPABILITIES = {
    "location": {
        "dex_strings": [b"requestLocationUpdates", b"getLastLocation", b"FusedLocationProviderClient", b"getFusedLocationProviderClient"],
        "android_permissions": ["android.permission.ACCESS_FINE_LOCATION", "android.permission.ACCESS_COARSE_LOCATION"],
        "ios_purpose_keys": ["NSLocationWhenInUseUsageDescription", "NSLocationAlwaysAndWhenInUseUsageDescription", "NSLocationAlwaysUsageDescription"],
        "dex_prefixes": [b"Landroid/location/LocationManager", b"Lcom/google/android/gms/location/FusedLocationProviderClient", b"Lcom/google/android/gms/location/LocationServices"],
        "ios_frameworks": ["CoreLocation"],
        "ios_selectors": [b"requestWhenInUseAuthorization", b"startUpdatingLocation", b"requestLocation"],
    },
    "background-location": {
        "dex_strings": [b"getGeofencingClient", b"addGeofences", b"GeofencingRequest", b"removeGeofences"],
        "android_permissions": ["android.permission.ACCESS_BACKGROUND_LOCATION"],
        "ios_purpose_keys": ["NSLocationAlwaysAndWhenInUseUsageDescription", "NSLocationAlwaysUsageDescription"],
        "dex_prefixes": [b"Lcom/google/android/gms/location/GeofencingClient", b"Lcom/google/android/gms/location/Geofence"],
        "ios_frameworks": ["CoreLocation"],
        "ios_selectors": [b"requestAlwaysAuthorization", b"startMonitoringForRegion:", b"allowsBackgroundLocationUpdates", b"startMonitoringSignificantLocationChanges"],
        "ios_background_mode": "location",
    },
    "camera": {
        "dex_strings": [b"android.hardware.camera2", b"openCamera", b"CameraCharacteristics"],
        "android_permissions": ["android.permission.CAMERA"],
        "ios_purpose_keys": ["NSCameraUsageDescription"],
        "dex_prefixes": [b"Landroid/hardware/camera2/", b"Landroid/hardware/Camera;", b"Landroidx/camera/"],
        "ios_frameworks": ["AVFoundation"],
        "ios_selectors": [b"AVCaptureDevice", b"AVCaptureSession"],
    },
    "photos": {
        "dex_strings": [b"android.provider.MediaStore", b"ACTION_PICK_IMAGES", b"PickVisualMedia"],
        "android_permissions": ["android.permission.READ_MEDIA_IMAGES", "android.permission.READ_EXTERNAL_STORAGE"],
        "ios_purpose_keys": ["NSPhotoLibraryUsageDescription", "NSPhotoLibraryAddUsageDescription"],
        "dex_prefixes": [b"Landroid/provider/MediaStore"],
        "ios_frameworks": ["Photos", "PhotosUI"],
        "ios_selectors": [b"PHPickerViewController", b"UIImagePickerController", b"PHPhotoLibrary"],
    },
    "microphone": {
        "dex_strings": [b"AudioRecord", b"MediaRecorder"],
        "android_permissions": ["android.permission.RECORD_AUDIO"],
        "ios_purpose_keys": ["NSMicrophoneUsageDescription"],
        "dex_prefixes": [b"Landroid/media/AudioRecord", b"Landroid/media/MediaRecorder"],
        "ios_frameworks": ["AVFoundation"],
        "ios_selectors": [b"AVAudioRecorder", b"AVAudioSession"],
    },
    "contacts": {
        "dex_strings": [b"ContactsContract"],
        "android_permissions": ["android.permission.READ_CONTACTS", "android.permission.WRITE_CONTACTS"],
        "ios_purpose_keys": ["NSContactsUsageDescription"],
        "dex_prefixes": [b"Landroid/provider/ContactsContract"],
        "ios_frameworks": ["Contacts", "ContactsUI"],
        "ios_selectors": [b"CNContactStore"],
    },
    "notifications": {
        "dex_strings": [b"NotificationManager", b"NotificationChannel"],
        "android_permissions": ["android.permission.POST_NOTIFICATIONS"],
        "ios_purpose_keys": [],
        "dex_prefixes": [b"Landroid/app/NotificationManager", b"Landroidx/core/app/NotificationManagerCompat"],
        "ios_frameworks": ["UserNotifications"],
        "ios_selectors": [b"requestAuthorizationWithOptions:completionHandler:", b"UNUserNotificationCenter"],
        "ios_background_mode": "remote-notification",
    },
    "bluetooth": {
        "dex_strings": [b"BluetoothAdapter", b"BluetoothLeScanner"],
        "android_permissions": ["android.permission.BLUETOOTH_CONNECT", "android.permission.BLUETOOTH_SCAN", "android.permission.BLUETOOTH"],
        "ios_purpose_keys": ["NSBluetoothAlwaysUsageDescription", "NSBluetoothPeripheralUsageDescription"],
        "dex_prefixes": [b"Landroid/bluetooth/"],
        "ios_frameworks": ["CoreBluetooth"],
        "ios_selectors": [b"CBCentralManager"],
    },
    "health": {
        "dex_strings": [b"HealthConnectClient", b"SensorManager"],
        "android_permissions": ["android.permission.health.READ_STEPS", "android.permission.BODY_SENSORS", "android.permission.ACTIVITY_RECOGNITION"],
        "ios_purpose_keys": ["NSHealthShareUsageDescription", "NSHealthUpdateUsageDescription", "NSMotionUsageDescription"],
        "dex_prefixes": [b"Landroidx/health/connect/", b"Landroid/hardware/SensorManager"],
        "ios_frameworks": ["HealthKit", "CoreMotion"],
        "ios_selectors": [b"HKHealthStore", b"CMMotionActivityManager", b"CMPedometer"],
    },
    "tracking": {
        "dex_strings": [b"AdvertisingIdClient", b"getAdvertisingIdInfo"],
        "android_permissions": ["com.google.android.gms.permission.AD_ID"],
        "ios_purpose_keys": ["NSUserTrackingUsageDescription"],
        "dex_prefixes": [b"Lcom/google/android/gms/ads/identifier/AdvertisingIdClient"],
        "ios_frameworks": ["AppTrackingTransparency", "AdSupport"],
        "ios_selectors": [b"requestTrackingAuthorizationWithCompletionHandler:", b"advertisingIdentifier"],
    },
}

# Purpose-string keys Apple actually defines. A key outside this set in Info.plist
# is a typo or an invention and does nothing.
APPLE_PURPOSE_KEYS = {
    "NSBluetoothAlwaysUsageDescription", "NSBluetoothPeripheralUsageDescription", "NSCalendarsUsageDescription",
    "NSCalendarsFullAccessUsageDescription", "NSCalendarsWriteOnlyAccessUsageDescription", "NSCameraUsageDescription",
    "NSContactsUsageDescription", "NSFaceIDUsageDescription", "NSHealthShareUsageDescription",
    "NSHealthUpdateUsageDescription", "NSHealthClinicalHealthRecordsShareUsageDescription", "NSHomeKitUsageDescription",
    "NSLocationAlwaysAndWhenInUseUsageDescription", "NSLocationAlwaysUsageDescription", "NSLocationUsageDescription",
    "NSLocationWhenInUseUsageDescription", "NSLocationTemporaryUsageDescriptionDictionary", "NSMicrophoneUsageDescription",
    "NSMotionUsageDescription", "NSFallDetectionUsageDescription", "NSPhotoLibraryUsageDescription",
    "NSPhotoLibraryAddUsageDescription", "NSRemindersUsageDescription", "NSRemindersFullAccessUsageDescription",
    "NSSiriUsageDescription", "NSSpeechRecognitionUsageDescription", "NSUserTrackingUsageDescription",
    "NSLocalNetworkUsageDescription", "NSNearbyInteractionUsageDescription", "NSNearbyInteractionAllowOnceUsageDescription",
    "NSAppleMusicUsageDescription", "NSVideoSubscriberAccountUsageDescription", "NSSensorKitUsageDescription",
    "NSIdentityUsageDescription", "NSFocusStatusUsageDescription", "NSGKFriendListUsageDescription",
    "NSWorldSensingUsageDescription", "NSHandsTrackingUsageDescription", "NFCReaderUsageDescription",
    "NSVoIPUsageDescription", "NSAccessibilityUsageDescription", "NSBluetoothWhileInUseUsageDescription",
    "NSCameraUsageDescription", "NSDesktopFolderUsageDescription", "NSDocumentsFolderUsageDescription",
    "NSDownloadsFolderUsageDescription", "NSFileProviderPresenceUsageDescription", "NSFileProviderDomainUsageDescription",
    "NSNetworkVolumesUsageDescription", "NSRemovableVolumesUsageDescription", "NSSystemAdministrationUsageDescription",
    "NSSystemExtensionUsageDescription", "NSUserActivityUsageDescription",
}


# Signals: things an app does that decide whether whole families of rules apply.
# Read from the binaries like capabilities, but they gate rules rather than permissions.
SIGNALS = {
    "login":    {"dex": [b"Lcom/google/firebase/auth/", b"Lcom/facebook/login/", b"Lcom/google/android/gms/auth/"],
                 "ios_frameworks": ["AuthenticationServices"], "ios_strings": [b"FIRAuth", b"ASAuthorizationController", b"signInWithEmail"]},
    "purchases": {"dex": [b"Lcom/android/billingclient/", b"Lcom/android/vending/billing/"],
                  "ios_frameworks": ["StoreKit"], "ios_strings": [b"SKPaymentQueue", b"SKProduct", b"StoreKit"]},
    "ads":      {"dex": [b"Lcom/google/android/gms/ads/", b"Lcom/facebook/ads/", b"Lcom/unity3d/ads/"],
                 "ios_frameworks": ["GoogleMobileAds", "AdSupport"], "ios_strings": [b"GADMobileAds", b"GADBannerView"]},
    "webview":  {"dex": [b"Landroid/webkit/WebView"], "ios_frameworks": ["WebKit"], "ios_strings": [b"WKWebView"]},
    "vpn":      {"dex": [b"Landroid/net/VpnService"], "ios_frameworks": ["NetworkExtension"], "ios_strings": [b"NEVPNManager", b"NETunnelProvider"]},
    "maps":     {"dex": [b"Lcom/google/android/gms/maps/"], "ios_frameworks": ["MapKit"], "ios_strings": [b"MKMapView", b"GMSMapView"]},
    "push":     {"dex": [b"Lcom/google/firebase/messaging/"], "ios_frameworks": ["UserNotifications"], "ios_strings": [b"registerForRemoteNotifications"]},
    "healthkit": {"dex": [b"Landroidx/health/connect/"], "ios_frameworks": ["HealthKit"], "ios_strings": [b"HKHealthStore"]},
    "crypto":   {"dex": [b"Lorg/web3j/", b"Lwallet/core/"], "ios_frameworks": [], "ios_strings": [b"web3", b"WalletCore"]},
    "gambling": {"dex": [], "ios_frameworks": [], "ios_strings": []},
    "streaming-games": {"dex": [], "ios_frameworks": [], "ios_strings": []},
    "device-management": {"dex": [b"Landroid/app/admin/DevicePolicyManager"], "ios_frameworks": ["ManagedAppDistribution"], "ios_strings": [b"NEHotspotConfiguration"]},
    "social-login": {"dex": [b"Lcom/facebook/login/", b"Lcom/google/android/gms/auth/api/signin/", b"Lcom/twitter/sdk/android/core/identity/"],
                     "ios_frameworks": ["GoogleSignIn", "FBSDKLoginKit"], "ios_strings": [b"GIDSignIn", b"FBSDKLoginManager", b"LoginManager"]},
    "sign-in-with-apple": {"dex": [], "ios_frameworks": [], "ios_strings": [b"ASAuthorizationAppleIDProvider", b"ASAuthorizationAppleIDButton"]},
    "apple-pay": {"dex": [], "ios_frameworks": ["PassKit"], "ios_strings": [b"PKPaymentAuthorizationViewController", b"PKPaymentRequest"]},
    "arkit": {"dex": [], "ios_frameworks": ["ARKit"], "ios_strings": [b"ARSession"]},
    "third-party-analytics": {"dex": [b"Lcom/google/firebase/analytics/", b"Lcom/mixpanel/", b"Lcom/amplitude/", b"Lcom/segment/"],
                              "ios_frameworks": ["FirebaseAnalytics"], "ios_strings": [b"FIRAnalytics", b"Mixpanel", b"Amplitude"]},
}
