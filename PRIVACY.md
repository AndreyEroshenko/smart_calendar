# Privacy Policy — smart_calendar

_Last updated: 14 November 2026_

smart_calendar ("the app") is a private, non-commercial tool run by one person for their own family. Family members
forward event details (invitations, tickets, bookings) to a Telegram bot, the app suggests calendar events, and after
the user confirms them it adds them to the family's Google Calendar. The app is not offered to the public.

## What data the app handles

- **Messages you send to the bot**: text, photos and PDFs that you forward or send to the Telegram bot, plus your
  Telegram user ID and chat ID.
- **Event suggestions**: the event details extracted from those messages (title, date, time, location, notes).
- **Google Calendar access**: an OAuth token that lets the app create events in the chosen calendar and read the list
  of calendars so the right one can be selected.

## How the data is used

- Messages are sent to Anthropic's Claude API only to extract event details from them.
- Extracted events are shown back to you in Telegram for confirmation. Only events you confirm are added to Google
  Calendar.
- Telegram user IDs are used to restrict the bot to approved family members.

The app does not use the data for advertising, profiling, analytics or any purpose other than creating the calendar
events you ask for, and it does not sell or share data with anyone else.

## Google user data

The app requests these Google Calendar scopes:

- `https://www.googleapis.com/auth/calendar.events`: to create the events you confirm.
- `https://www.googleapis.com/auth/calendar.readonly`: to list your calendars so the target calendar can be chosen.

The app's use and transfer of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including
the Limited Use requirements. Google user data is not transferred to third parties, is not used for advertising, and is
not used to train AI models.

## Third-party services

The app relies on these services, each with its own privacy policy:

- [Telegram](https://telegram.org/privacy), to receive messages and reply to you.
- [Anthropic](https://www.anthropic.com/legal/privacy), to extract event details from message content. Under
  Anthropic's commercial terms, API inputs are not used to train its models.
- [Google Calendar](https://policies.google.com/privacy), to store the events.

## Storage and retention

The app runs on a private server. The message text and extracted event suggestions are kept in a local database on
that server so that pending suggestions can be confirmed or edited, and the Google OAuth token is stored on the same
server. Photos and PDFs are not stored after processing. Nothing is stored elsewhere.

You can ask for your stored data to be deleted at any time. You can revoke the app's Google access at any time at
<https://myaccount.google.com/permissions>.

## Contact

For questions or deletion requests, contact the app's owner directly or open an issue at
<https://github.com/AndreyEroshenko/smart_calendar/issues>.

## Changes

This policy may be updated as the app changes. The current version is always at this address.
