#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <Foundation/Foundation.h>

static NSString *const ClaudeBundleIdentifier = @"com.anthropic.claudefordesktop";

static void Emit(NSDictionary *payload, int exitCode) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:payload
                                                   options:NSJSONWritingSortedKeys
                                                     error:nil];
    [[NSFileHandle fileHandleWithStandardOutput] writeData:data];
    [[NSFileHandle fileHandleWithStandardOutput]
        writeData:[NSData dataWithBytes:"\n" length:1]];
    exit(exitCode);
}

static id CopyAttribute(AXUIElementRef element, CFStringRef attribute) {
    CFTypeRef value = NULL;
    if (AXUIElementCopyAttributeValue(element, attribute, &value) != kAXErrorSuccess ||
        value == NULL) {
        return nil;
    }
    return CFBridgingRelease(value);
}

static NSString *StringAttribute(AXUIElementRef element, CFStringRef attribute) {
    id value = CopyAttribute(element, attribute);
    return [value isKindOfClass:NSString.class] ? value : nil;
}

static NSNumber *BoolAttribute(AXUIElementRef element, CFStringRef attribute) {
    id value = CopyAttribute(element, attribute);
    return [value isKindOfClass:NSNumber.class] ? value : nil;
}

static NSArray *Descendants(AXUIElementRef root) {
    NSMutableArray *queue = [NSMutableArray arrayWithObject:(__bridge id)root];
    NSMutableArray<NSNumber *> *depths = [NSMutableArray arrayWithObject:@0];
    NSMutableArray *result = [NSMutableArray array];
    NSUInteger index = 0;
    const NSUInteger limit = 8000;
    const NSInteger maxDepth = 40;

    while (index < queue.count && result.count < limit) {
        id object = queue[index];
        NSInteger depth = depths[index].integerValue;
        index += 1;
        [result addObject:object];
        if (depth >= maxDepth) {
            continue;
        }

        AXUIElementRef element = (__bridge AXUIElementRef)object;
        for (NSString *attribute in @[(__bridge NSString *)kAXChildrenAttribute,
                                      (__bridge NSString *)kAXContentsAttribute]) {
            id children = CopyAttribute(element, (__bridge CFStringRef)attribute);
            if (![children isKindOfClass:NSArray.class]) {
                continue;
            }
            for (id child in (NSArray *)children) {
                [queue addObject:child];
                [depths addObject:@(depth + 1)];
            }
        }
    }
    return result;
}

static NSString *SearchableText(AXUIElementRef element) {
    NSArray<NSString *> *attributes = @[
        (__bridge NSString *)kAXTitleAttribute,
        (__bridge NSString *)kAXDescriptionAttribute,
        (__bridge NSString *)kAXHelpAttribute,
        (__bridge NSString *)kAXValueAttribute,
        (__bridge NSString *)kAXPlaceholderValueAttribute,
    ];
    NSMutableArray<NSString *> *parts = [NSMutableArray array];
    for (NSString *attribute in attributes) {
        NSString *value = StringAttribute(element, (__bridge CFStringRef)attribute);
        if (value != nil) {
            [parts addObject:value];
        }
    }
    return [parts componentsJoinedByString:@"\n"];
}

static void PostReturnKey(void) {
    CGEventSourceRef source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState);
    CGEventRef keyDown = CGEventCreateKeyboardEvent(source, 36, true);
    CGEventRef keyUp = CGEventCreateKeyboardEvent(source, 36, false);
    CGEventPost(kCGHIDEventTap, keyDown);
    CGEventPost(kCGHIDEventTap, keyUp);
    if (keyDown != NULL) CFRelease(keyDown);
    if (keyUp != NULL) CFRelease(keyUp);
    if (source != NULL) CFRelease(source);
}

static NSString *ArgumentAfter(NSString *flag, NSArray<NSString *> *arguments) {
    NSUInteger index = [arguments indexOfObject:flag];
    if (index == NSNotFound || index + 1 >= arguments.count) {
        return nil;
    }
    return arguments[index + 1];
}

static NSInteger ComposerScore(AXUIElementRef element) {
    NSString *role = StringAttribute(element, kAXRoleAttribute) ?: @"";
    if (![role isEqualToString:(__bridge NSString *)kAXTextAreaRole] &&
        ![role isEqualToString:(__bridge NSString *)kAXTextFieldRole]) {
        return -1;
    }
    if ([BoolAttribute(element, kAXEnabledAttribute) isEqualToNumber:@NO]) {
        return -1;
    }

    NSInteger score = 0;
    if ([role isEqualToString:(__bridge NSString *)kAXTextAreaRole]) score += 20;
    if ([BoolAttribute(element, kAXFocusedAttribute) isEqualToNumber:@YES]) score += 100;
    NSString *text = SearchableText(element).lowercaseString;
    if ([text containsString:@"write a message"] ||
        [text containsString:@"message claude"] ||
        [text containsString:@"输入消息"]) {
        score += 80;
    }
    return score;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSMutableArray<NSString *> *arguments = [NSMutableArray array];
        for (int index = 1; index < argc; index++) {
            [arguments addObject:[NSString stringWithUTF8String:argv[index]]];
        }

        if ([arguments containsObject:@"--request-accessibility"]) {
            NSDictionary *options = @{
                (__bridge NSString *)kAXTrustedCheckOptionPrompt: @YES
            };
            BOOL trusted = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
            Emit(
                @{
                    @"ok": @(trusted),
                    @"trusted": @(trusted),
                    @"message": trusted
                        ? @"Accessibility permission is available."
                        : @"Grant Accessibility permission to ReSETP Claude Quota Watchdog Helper in System Settings > Privacy & Security > Accessibility.",
                },
                trusted ? 0 : 2
            );
        }

        if ([arguments containsObject:@"--list-system-settings-windows"]) {
            NSArray *windows = CFBridgingRelease(
                CGWindowListCopyWindowInfo(
                    kCGWindowListOptionAll,
                    kCGNullWindowID
                )
            );
            NSMutableArray *matches = [NSMutableArray array];
            for (NSDictionary *window in windows) {
                NSString *owner = window[(__bridge NSString *)kCGWindowOwnerName];
                if ([owner isEqualToString:@"System Settings"]) {
                    [matches addObject:window];
                }
            }
            Emit(@{@"ok": @YES, @"windows": matches}, 0);
        }

        if ([arguments containsObject:@"--activate-system-settings"]) {
            NSRunningApplication *settings =
                [NSRunningApplication runningApplicationsWithBundleIdentifier:
                    @"com.apple.systempreferences"].firstObject;
            BOOL activated = NO;
            if (settings != nil) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
                activated = [settings activateWithOptions:
                    NSApplicationActivateAllWindows |
                    NSApplicationActivateIgnoringOtherApps];
#pragma clang diagnostic pop
            }
            Emit(@{@"ok": @(activated)}, activated ? 0 : 3);
        }

        if (!AXIsProcessTrusted()) {
            Emit(
                @{
                    @"ok": @NO,
                    @"trusted": @NO,
                    @"error": @"ACCESSIBILITY_NOT_AUTHORIZED",
                    @"message": @"Grant Accessibility permission to ReSETP Claude Quota Watchdog Helper in System Settings > Privacy & Security > Accessibility.",
                },
                2
            );
        }

        if ([arguments containsObject:@"--probe"]) {
            Emit(@{@"ok": @YES, @"trusted": @YES}, 0);
        }

        NSString *message = ArgumentAfter(@"--message", arguments);
        if (![arguments containsObject:@"--send"] || message.length == 0) {
            Emit(@{@"ok": @NO, @"error": @"INVALID_ARGUMENTS"}, 64);
        }
        NSString *expectedTitle = ArgumentAfter(@"--expect-title", arguments);

        NSRunningApplication *claude =
            [NSRunningApplication runningApplicationsWithBundleIdentifier:ClaudeBundleIdentifier].firstObject;
        if (claude == nil) {
            Emit(@{@"ok": @NO, @"error": @"CLAUDE_NOT_RUNNING"}, 3);
        }

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        [claude activateWithOptions:NSApplicationActivateIgnoringOtherApps];
#pragma clang diagnostic pop
        [NSThread sleepForTimeInterval:1.0];

        AXUIElementRef appElement = AXUIElementCreateApplication(claude.processIdentifier);
        NSArray *nodes = Descendants(appElement);

        if (expectedTitle.length > 0) {
            BOOL titleFound = NO;
            for (id object in nodes) {
                if ([SearchableText((__bridge AXUIElementRef)object) containsString:expectedTitle]) {
                    titleFound = YES;
                    break;
                }
            }
            if (!titleFound) {
                CFRelease(appElement);
                Emit(
                    @{
                        @"ok": @NO,
                        @"error": @"EXPECTED_SESSION_TITLE_NOT_FOUND",
                        @"expected_title": expectedTitle,
                    },
                    4
                );
            }
        }

        AXUIElementRef composer = NULL;
        NSInteger bestScore = -1;
        for (id object in nodes) {
            AXUIElementRef element = (__bridge AXUIElementRef)object;
            NSInteger score = ComposerScore(element);
            if (score > bestScore) {
                bestScore = score;
                composer = element;
            }
        }
        if (composer == NULL) {
            CFRelease(appElement);
            Emit(@{@"ok": @NO, @"error": @"COMPOSER_NOT_FOUND"}, 5);
        }

        if (AXUIElementSetAttributeValue(composer, kAXFocusedAttribute, kCFBooleanTrue) !=
            kAXErrorSuccess) {
            CFRelease(appElement);
            Emit(@{@"ok": @NO, @"error": @"COMPOSER_FOCUS_FAILED"}, 6);
        }
        if (AXUIElementSetAttributeValue(
                composer, kAXValueAttribute, (__bridge CFTypeRef)message
            ) != kAXErrorSuccess) {
            CFRelease(appElement);
            Emit(@{@"ok": @NO, @"error": @"COMPOSER_SET_VALUE_FAILED"}, 7);
        }

        [NSThread sleepForTimeInterval:0.35];
        NSString *valueBeforeSend = StringAttribute(composer, kAXValueAttribute);
        if (![valueBeforeSend isEqualToString:message]) {
            CFRelease(appElement);
            Emit(
                @{
                    @"ok": @NO,
                    @"error": @"COMPOSER_VALUE_VERIFICATION_FAILED",
                    @"observed_length": @(valueBeforeSend == nil ? -1 : valueBeforeSend.length),
                },
                8
            );
        }

        PostReturnKey();
        [NSThread sleepForTimeInterval:1.5];

        nodes = Descendants(appElement);
        BOOL messageVisible = NO;
        for (id object in nodes) {
            if ([SearchableText((__bridge AXUIElementRef)object) containsString:message]) {
                messageVisible = YES;
                break;
            }
        }
        BOOL composerCleared =
            (StringAttribute(composer, kAXValueAttribute) ?: @"").length == 0;
        CFRelease(appElement);

        if (!messageVisible || !composerCleared) {
            Emit(
                @{
                    @"ok": @NO,
                    @"error": @"SEND_NOT_CONFIRMED",
                    @"message_visible": @(messageVisible),
                    @"composer_cleared": @(composerCleared),
                },
                9
            );
        }

        Emit(
            @{
                @"ok": @YES,
                @"trusted": @YES,
                @"message_visible": @YES,
                @"composer_cleared": @YES,
            },
            0
        );
    }
}
