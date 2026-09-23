use AppleScript version "2.7"
use framework "Foundation"
use scripting additions

on run argv
    try
        if (count of argv) is not 1 then error "Expected one request JSON path" number 9001
        set requestObject to my loadJSON(item 1 of argv)
        set commandName to my requestText(requestObject, "command", "")
        if commandName is "status" then
            set responseObject to my commandStatus()
        else if commandName is "accounts" then
            set responseObject to my commandAccounts()
        else if commandName is "mailboxes" then
            set responseObject to my commandMailboxes(requestObject)
        else if commandName is "search" then
            set responseObject to my commandSearch(requestObject)
        else if commandName is "locate" then
            set responseObject to my commandLocate(requestObject)
        else if commandName is "recent" then
            set responseObject to my commandRecent(requestObject)
        else if commandName is "inspect" then
            set responseObject to my commandInspect(requestObject)
        else if commandName is "read" then
            set responseObject to my commandRead(requestObject)
        else if commandName is "read_role_message" then
            set responseObject to my commandReadRoleMessage(requestObject)
        else if commandName is "count_sent" then
            set responseObject to my commandCountSent(requestObject)
        else if commandName is "draft_new" then
            set responseObject to my commandDraftNew(requestObject)
        else if commandName is "draft_reply" then
            set responseObject to my commandDraftReply(requestObject)
        else if commandName is "draft_forward" then
            set responseObject to my commandDraftForward(requestObject)
        else if commandName is "send_plan" then
            set responseObject to my commandSendPlan(requestObject)
        else if commandName is "outgoing_status" then
            set responseObject to my commandOutgoingStatus(requestObject)
        else if commandName is "apply_action" then
            set responseObject to my commandApplyAction(requestObject)
        else if commandName is "act" then
            set responseObject to my commandAct(requestObject)
        else
            error "Unsupported command: " & commandName number 9002
        end if
        return my jsonString(responseObject)
    on error errorMessage number errorNumber
        set errorObject to my newDictionary()
        my putValue(errorObject, "ok", false)
        my putValue(errorObject, "code", "MAIL_APPLESCRIPT_" & errorNumber)
        my putValue(errorObject, "error", errorMessage)
        return my jsonString(errorObject)
    end try
end run


on loadJSON(posixPath)
    set jsonData to current application's NSData's dataWithContentsOfFile:posixPath
    if jsonData is missing value then error "Unable to read request JSON" number 9003
    set jsonObject to current application's NSJSONSerialization's JSONObjectWithData:jsonData options:0 |error|:(missing value)
    if jsonObject is missing value then error "Unable to parse request JSON" number 9004
    return jsonObject
end loadJSON


on jsonString(jsonObject)
    set jsonData to current application's NSJSONSerialization's dataWithJSONObject:jsonObject options:0 |error|:(missing value)
    if jsonData is missing value then error "Unable to encode response JSON" number 9005
    return (current application's NSString's alloc()'s initWithData:jsonData encoding:(current application's NSUTF8StringEncoding)) as text
end jsonString


on newDictionary()
    return current application's NSMutableDictionary's dictionary()
end newDictionary


on newArray()
    return current application's NSMutableArray's array()
end newArray


on putValue(targetDictionary, keyName, theValue)
    if theValue is missing value then
        return
    else
        targetDictionary's setObject:theValue forKey:keyName
    end if
end putValue


on addValue(targetArray, theValue)
    if theValue is missing value then
        return
    else
        targetArray's addObject:theValue
    end if
end addValue


on requestValue(requestObject, keyName)
    set theValue to requestObject's objectForKey:keyName
    if theValue is missing value then return missing value
    if (theValue's isKindOfClass:(current application's NSNull)) as boolean then return missing value
    return theValue
end requestValue


on requestText(requestObject, keyName, defaultValue)
    set theValue to my requestValue(requestObject, keyName)
    if theValue is missing value then return defaultValue
    return theValue as text
end requestText


on requestInteger(requestObject, keyName, defaultValue)
    set theValue to my requestValue(requestObject, keyName)
    if theValue is missing value then return defaultValue
    return theValue as integer
end requestInteger


on requestReal(requestObject, keyName, defaultValue)
    set theValue to my requestValue(requestObject, keyName)
    if theValue is missing value then return defaultValue
    return theValue as real
end requestReal


on requestBoolean(requestObject, keyName, defaultValue)
    set theValue to my requestValue(requestObject, keyName)
    if theValue is missing value then return defaultValue
    return theValue as boolean
end requestBoolean


on requestTextList(requestObject, keyName)
    set arrayValue to my requestValue(requestObject, keyName)
    if arrayValue is missing value then return {}
    set resultList to {}
    set itemCount to arrayValue's |count|() as integer
    repeat with itemIndex from 0 to (itemCount - 1)
        set end of resultList to (arrayValue's objectAtIndex:itemIndex) as text
    end repeat
    return resultList
end requestTextList


on requestIntegerList(requestObject, keyName)
    set arrayValue to my requestValue(requestObject, keyName)
    if arrayValue is missing value then return {}
    set resultList to {}
    set itemCount to arrayValue's |count|() as integer
    repeat with itemIndex from 0 to (itemCount - 1)
        set end of resultList to (arrayValue's objectAtIndex:itemIndex) as integer
    end repeat
    return resultList
end requestIntegerList


on foundationArray(textItems)
    set resultArray to my newArray()
    repeat with textItem in textItems
        my addValue(resultArray, textItem as text)
    end repeat
    return resultArray
end foundationArray


on normalizedText(theText)
    return ((current application's NSString's stringWithString:(theText as text))'s precomposedStringWithCanonicalMapping()) as text
end normalizedText


on normalizedLower(theText)
    return (((current application's NSString's stringWithString:(theText as text))'s precomposedStringWithCanonicalMapping())'s lowercaseString()) as text
end normalizedLower


on normalizedContentText(theText)
    set valueText to current application's NSString's stringWithString:(theText as text)
    set valueText to valueText's stringByReplacingOccurrencesOfString:(return & linefeed) withString:linefeed
    set valueText to valueText's stringByReplacingOccurrencesOfString:return withString:linefeed
    set valueText to valueText's stringByTrimmingCharactersInSet:(current application's NSCharacterSet's whitespaceAndNewlineCharacterSet())
    return (valueText's precomposedStringWithCanonicalMapping()) as text
end normalizedContentText


on normalizedIdentity(theText)
    set valueText to current application's NSString's stringWithString:(theText as text)
    set valueText to valueText's precomposedStringWithCanonicalMapping()
    set valueText to valueText's lowercaseString()
    set valueText to valueText's componentsSeparatedByCharactersInSet:(current application's NSCharacterSet's punctuationCharacterSet())
    set valueText to valueText's componentsJoinedByString:" "
    set valueText to valueText's componentsSeparatedByCharactersInSet:(current application's NSCharacterSet's whitespaceAndNewlineCharacterSet())
    -- Preserve empty components. Callers skip them while iterating, avoiding a
    -- per-candidate Foundation filter allocation during Mail searches.
    return (valueText's componentsJoinedByString:" ") as text
end normalizedIdentity


on identityMatches(senderText, identityText)
    if identityText is "" then return true
    set normalizedSender to my normalizedIdentity(senderText)
    set identityTokens to (current application's NSString's stringWithString:(my normalizedIdentity(identityText)))'s componentsSeparatedByString:" "
    set tokenCount to identityTokens's |count|() as integer
    repeat with tokenIndex from 0 to (tokenCount - 1)
        set tokenText to (identityTokens's objectAtIndex:tokenIndex) as text
        if tokenText is not "" and normalizedSender does not contain tokenText then return false
    end repeat
    return true
end identityMatches


on firstIdentityToken(identityText)
    set identityTokens to (current application's NSString's stringWithString:(my normalizedIdentity(identityText)))'s componentsSeparatedByString:" "
    set tokenCount to identityTokens's |count|() as integer
    repeat with tokenIndex from 0 to (tokenCount - 1)
        set tokenText to (identityTokens's objectAtIndex:tokenIndex) as text
        if tokenText is not "" then return tokenText
    end repeat
    return ""
end firstIdentityToken


on textEquals(leftText, rightText)
    return (my normalizedText(leftText)) is (my normalizedText(rightText))
end textEquals


on joinPath(pathItems)
    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to " / "
    set joinedText to pathItems as text
    set AppleScript's text item delimiters to oldDelimiters
    return joinedText
end joinPath


using terms from application "Mail"
    on resolveAccount(accountQuery)
        tell application "Mail"
            set matches to {}
            set accountItems to accounts
            repeat with anAccount in accountItems
                set accountName to name of anAccount as text
                set accountID to (get id of anAccount) as text
                if my textEquals(accountQuery, accountName) or my textEquals(accountQuery, accountID) then set end of matches to anAccount
            end repeat
            if (count of matches) is 1 then return item 1 of matches
            if (count of matches) > 1 then error "Mail account name or ID is ambiguous" number 9101
            repeat with anAccount in accountItems
                set accountAddresses to email addresses of anAccount
                repeat with anAddress in accountAddresses
                    if (my normalizedLower(accountQuery)) is (my normalizedLower(anAddress as text)) then
                        set end of matches to anAccount
                        exit repeat
                    end if
                end repeat
            end repeat
            if (count of matches) is not 1 then error "Expected one Mail account for '" & accountQuery & "'; found " & (count of matches) number 9101
            return item 1 of matches
        end tell
    end resolveAccount


    on resolveMailbox(anAccount, pathItems)
        tell application "Mail"
            if (count of pathItems) is 0 then error "Mailbox path is empty" number 9102
            set currentMailboxes to mailboxes of anAccount
            set selectedMailbox to missing value
            repeat with pathPart in pathItems
                set matches to {}
                repeat with candidateMailbox in currentMailboxes
                    if my textEquals(name of candidateMailbox as text, pathPart as text) then set end of matches to candidateMailbox
                end repeat
                if (count of matches) is not 1 then error "Expected one mailbox path segment '" & (pathPart as text) & "'; found " & (count of matches) number 9103
                set selectedMailbox to item 1 of matches
                set currentMailboxes to mailboxes of selectedMailbox
            end repeat
            return selectedMailbox
        end tell
    end resolveMailbox


    on roleMailbox(roleName)
        tell application "Mail"
            if roleName is "drafts" then return drafts mailbox
            if roleName is "sent" then return sent mailbox
            if roleName is "inbox" then return inbox
            if roleName is "trash" then return trash mailbox
            if roleName is "junk" then return junk mailbox
            error "Unsupported role mailbox: " & roleName number 9105
        end tell
    end roleMailbox


    on pathFromRequest(requestObject, keyName)
        set pathValue to my requestValue(requestObject, keyName)
        if pathValue is missing value then return {}
        set pathItems to {}
        set itemCount to pathValue's |count|() as integer
        repeat with itemIndex from 0 to (itemCount - 1)
            set end of pathItems to (pathValue's objectAtIndex:itemIndex) as text
        end repeat
        return pathItems
    end pathFromRequest


    on refParts(referenceObject)
        set accountQuery to my requestText(referenceObject, "account", "")
        set localID to my requestInteger(referenceObject, "local_id", -1)
        set expectedRFCID to my requestText(referenceObject, "rfc_message_id", "")
        set expectedUniversalID to my requestText(referenceObject, "universal_id", "")
        set pathItems to my pathFromRequest(referenceObject, "mailbox_path")
        return {accountQuery, pathItems, localID, expectedRFCID, expectedUniversalID}
    end refParts


    on referenceWithMailboxPath(referenceObject, pathItems)
        set {accountQuery, ignoredPath, localID, expectedRFCID, expectedUniversalID} to my refParts(referenceObject)
        set updatedReference to my newDictionary()
        my putValue(updatedReference, "account", accountQuery)
        my putValue(updatedReference, "mailbox_path", my foundationArray(pathItems))
        my putValue(updatedReference, "local_id", localID)
        my putValue(updatedReference, "rfc_message_id", expectedRFCID)
        my putValue(updatedReference, "universal_id", expectedUniversalID)
        return updatedReference
    end referenceWithMailboxPath


    on messageHeaderValue(aMessage, headerName)
        tell application "Mail"
            try
                set rawHeaders to all headers of aMessage as text
                set headerPrefix to headerName & ":"
                repeat with aLine in paragraphs of rawHeaders
                    set lineText to aLine as text
                    if lineText starts with headerPrefix then
                        set valueText to text ((length of headerPrefix) + 1) thru -1 of lineText
                        return ((current application's NSString's stringWithString:valueText)'s stringByTrimmingCharactersInSet:(current application's NSCharacterSet's whitespaceCharacterSet())) as text
                    end if
                end repeat
            end try
            return ""
        end tell
    end messageHeaderValue


    on messageMatchesUniversalID(aMessage, expectedUniversalID)
        if expectedUniversalID is "" then return true
        return (my messageHeaderValue(aMessage, "X-Universally-Unique-Identifier")) is expectedUniversalID
    end messageMatchesUniversalID


    on resolveReferencedMessage(aMailbox, localID, expectedRFCID, expectedUniversalID, contextText, notFoundNumber)
        tell application "Mail"
            set matches to every message of aMailbox whose id is localID
            if (count of matches) > 1 then error "Expected one " & contextText & " with local id " & localID & "; found " & (count of matches) number 9112
            if (count of matches) is 1 then
                set aMessage to item 1 of matches
                if expectedUniversalID is not "" then
                    if not my messageMatchesUniversalID(aMessage, expectedUniversalID) then error "Universal message identifier mismatch" number 9111
                else if expectedRFCID is not "" then
                    try
                        if ((get message id of aMessage) as text) is not expectedRFCID then error "RFC Message-ID mismatch" number 9107
                    on error errorMessage number errorNumber
                        if errorNumber is 9107 then
                            error "RFC Message-ID mismatch" number 9107
                        else
                            error "Expected RFC Message-ID is unavailable" number 9108
                        end if
                    end try
                end if
                return aMessage
            end if

            if expectedRFCID is not "" then
                set matches to every message of aMailbox whose message id is expectedRFCID
                if (count of matches) is 1 then
                    set aMessage to item 1 of matches
                    if expectedUniversalID is "" or my messageMatchesUniversalID(aMessage, expectedUniversalID) then return aMessage
                    error "Universal message identifier mismatch" number 9111
                end if
                if (count of matches) > 1 then error "RFC Message-ID matched more than one " & contextText number 9112
            end if

            if expectedUniversalID is not "" then
                set universalMatches to {}
                repeat with candidateMessage in every message of aMailbox
                    if my messageMatchesUniversalID(candidateMessage, expectedUniversalID) then set end of universalMatches to candidateMessage
                end repeat
                if (count of universalMatches) is 1 then return item 1 of universalMatches
                if (count of universalMatches) > 1 then error "Universal message identifier matched more than one " & contextText number 9112
            end if
            error "Expected one " & contextText & " with its bound local, RFC, or universal identifier; found 0" number notFoundNumber
        end tell
    end resolveReferencedMessage


    on findMessage(referenceObject)
        set {accountQuery, pathItems, localID, expectedRFCID, expectedUniversalID} to my refParts(referenceObject)
        set anAccount to my resolveAccount(accountQuery)
        set aMailbox to my resolveMailbox(anAccount, pathItems)
        set aMessage to my resolveReferencedMessage(aMailbox, localID, expectedRFCID, expectedUniversalID, "message", 9106)
        return {anAccount, aMailbox, aMessage, pathItems}
    end findMessage


    on findRoleMessage(roleName, referenceObject)
        set {accountQuery, referencePath, localID, expectedRFCID, expectedUniversalID} to my refParts(referenceObject)
        set anAccount to my resolveAccount(accountQuery)
        if roleName is "drafts" and (count of referencePath) > 0 then
            set aRoleMailbox to my resolveMailbox(anAccount, referencePath)
        else
            set aRoleMailbox to my roleMailbox(roleName)
        end if
        set aMessage to my resolveReferencedMessage(aRoleMailbox, localID, expectedRFCID, expectedUniversalID, roleName & " message", 9109)
        tell application "Mail"
            try
                if ((get id of account of mailbox of aMessage) as text) is not ((get id of anAccount) as text) then error "Resolved role message belongs to another account" number 9110
            on error errorMessage number errorNumber
                if errorNumber is 9110 then error "Resolved role message belongs to another account" number 9110
            end try
            set underlyingPath to {name of mailbox of aMessage as text}
            return {anAccount, aRoleMailbox, aMessage, underlyingPath}
        end tell
    end findRoleMessage


    on resolveTrashedMessageForAccount(aTrashMailbox, anAccount, localID, expectedSubject, expectedRFCID)
        -- The account `trash mailbox` property is not populated by every Mail
        -- account type. Query the official aggregate Trash by the already bound
        -- local ID first, then prove the underlying mailbox belongs to this
        -- account. Gmail can re-key local IDs on a Trash move; in that case,
        -- narrow by the bound subject before comparing RFC IDs one
        -- candidate at a time. Never predicate the aggregate Trash by headers.
        tell application "Mail"
            set candidates to every message of aTrashMailbox whose id is localID
            set accountMatches to {}
            repeat with candidateMessage in candidates
                try
                    if ((get id of account of mailbox of candidateMessage) as text) is ((get id of anAccount) as text) then
                        if ((get message id of candidateMessage) as text) is expectedRFCID then set end of accountMatches to candidateMessage
                    end if
                end try
            end repeat
            if (count of accountMatches) is 1 then return item 1 of accountMatches
            if (count of accountMatches) > 1 then error "Validation message matched more than once in the selected account Trash" number 9304

            set subjectCandidates to every message of aTrashMailbox whose subject is expectedSubject
            set rekeyedMatches to {}
            repeat with candidateMessage in subjectCandidates
                try
                    if ((get id of account of mailbox of candidateMessage) as text) is ((get id of anAccount) as text) then
                        if ((get message id of candidateMessage) as text) is expectedRFCID then set end of rekeyedMatches to candidateMessage
                    end if
                end try
            end repeat
            if (count of rekeyedMatches) is 1 then return item 1 of rekeyedMatches
            if (count of rekeyedMatches) > 1 then error "Validation message matched more than once after Trash re-keying" number 9304
            error "Validation message was not found in the selected account Trash" number 9304
        end tell
    end resolveTrashedMessageForAccount


    on mailboxPathForMessage(aMessage)
        tell application "Mail"
            set pathItems to {}
            set currentMailbox to mailbox of aMessage
            repeat while currentMailbox is not missing value
                set pathItems to {name of currentMailbox as text} & pathItems
                try
                    set currentMailbox to container of currentMailbox
                on error
                    exit repeat
                end try
            end repeat
            return pathItems
        end tell
    end mailboxPathForMessage


    on accountTrashMailbox(aggregateTrash, anAccount)
        tell application "Mail"
            set matches to {}
            repeat with candidateMailbox in mailboxes of aggregateTrash
                try
                    if ((get id of account of candidateMailbox) as text) is ((get id of anAccount) as text) then set end of matches to candidateMailbox
                end try
            end repeat
            if (count of matches) is not 1 then error "Cannot identify one Trash mailbox for this account" number 9320
            return item 1 of matches
        end tell
    end accountTrashMailbox





    on recipientAddresses(aMessage, recipientKind)
        tell application "Mail"
            set resultList to {}
            if recipientKind is "to" then
                set recipientObjects to to recipients of aMessage
            else if recipientKind is "cc" then
                set recipientObjects to cc recipients of aMessage
            else
                set recipientObjects to bcc recipients of aMessage
            end if
            repeat with aRecipient in recipientObjects
                set end of resultList to address of aRecipient as text
            end repeat
            return resultList
        end tell
    end recipientAddresses


    on allRecipientAddresses(aMessage)
        return (my recipientAddresses(aMessage, "to")) & (my recipientAddresses(aMessage, "cc")) & (my recipientAddresses(aMessage, "bcc"))
    end allRecipientAddresses


    on sameAddressList(leftList, rightList)
        if (count of leftList) is not (count of rightList) then return false
        set normalizedLeft to {}
        set normalizedRight to {}
        repeat with anAddress in leftList
            set end of normalizedLeft to my normalizedLower(anAddress as text)
        end repeat
        repeat with anAddress in rightList
            set end of normalizedRight to my normalizedLower(anAddress as text)
        end repeat
        repeat with anAddress in normalizedLeft
            if normalizedRight does not contain anAddress then return false
        end repeat
        return true
    end sameAddressList


    on canonicalAddress(addressText)
        tell application "Mail"
            try
                return my normalizedLower(extract address from (addressText as text))
            on error
                return my normalizedLower(addressText as text)
            end try
        end tell
    end canonicalAddress


    on messageDictionary(aMessage, anAccount, pathItems, bodyMode, includeHeaders, includeSource)
        tell application "Mail"
            set resultObject to my newDictionary()
            set accountObject to my newDictionary()
            set accountName to name of anAccount as text
            set accountID to (get id of anAccount) as text
            my putValue(accountObject, "name", accountName)
            my putValue(accountObject, "id", accountID)
            my putValue(resultObject, "account", accountObject)
            my putValue(resultObject, "account_id", accountID)

            set localID to (get id of aMessage) as integer
            set rfcID to ""
            try
                set rfcID to (get message id of aMessage) as text
            end try
            set universalID to my messageHeaderValue(aMessage, "X-Universally-Unique-Identifier")
            set referenceObject to my newDictionary()
            my putValue(referenceObject, "account", accountName)
            my putValue(referenceObject, "mailbox_path", my foundationArray(pathItems))
            my putValue(referenceObject, "local_id", localID)
            my putValue(referenceObject, "rfc_message_id", rfcID)
            my putValue(referenceObject, "universal_id", universalID)
            my putValue(resultObject, "message_ref", referenceObject)
            my putValue(resultObject, "rfc_message_id", rfcID)
            my putValue(resultObject, "universal_id", universalID)
            my putValue(resultObject, "mailbox_path", my foundationArray(pathItems))
            my putValue(resultObject, "mailbox", my joinPath(pathItems))
            my putValue(resultObject, "sender", sender of aMessage as text)
            my putValue(resultObject, "subject", subject of aMessage as text)
            my putValue(resultObject, "to", my foundationArray(my recipientAddresses(aMessage, "to")))
            my putValue(resultObject, "cc", my foundationArray(my recipientAddresses(aMessage, "cc")))
            my putValue(resultObject, "bcc", my foundationArray(my recipientAddresses(aMessage, "bcc")))
            try
                my putValue(resultObject, "date_received", date received of aMessage as text)
            on error
                my putValue(resultObject, "date_received", "")
            end try
            try
                my putValue(resultObject, "date_sent", date sent of aMessage as text)
            on error
                my putValue(resultObject, "date_sent", "")
            end try
            try
                my putValue(resultObject, "read", read status of aMessage as boolean)
                my putValue(resultObject, "flagged", flagged status of aMessage as boolean)
            end try

            if bodyMode is not "none" then
                set bodyText to content of aMessage as text
                if bodyMode is "excerpt" and (length of bodyText) > 500 then set bodyText to text 1 thru 500 of bodyText
                my putValue(resultObject, "body", bodyText)
                my putValue(resultObject, "body_length", length of bodyText)
            end if
            if includeHeaders then
                try
                    my putValue(resultObject, "all_headers", all headers of aMessage as text)
                end try
            end if
            if includeSource then
                try
                    my putValue(resultObject, "source", source of aMessage as text)
                end try
            end if

            set attachmentArray to my newArray()
            try
                set messageAttachments to mail attachments of aMessage
            on error
                set messageAttachments to {}
            end try
            repeat with anAttachment in messageAttachments
                set attachmentObject to my newDictionary()
                set attachmentID to ""
                set attachmentName to ""
                set attachmentMIMEType to ""
                set attachmentFileSize to -1
                set attachmentDownloaded to false
                try
                    set attachmentID to (get id of anAttachment) as text
                end try
                try
                    set attachmentName to name of anAttachment as text
                end try
                try
                    set attachmentMIMEType to MIME type of anAttachment as text
                end try
                try
                    set attachmentFileSize to file size of anAttachment as integer
                end try
                try
                    set attachmentDownloaded to downloaded of anAttachment as boolean
                end try
                my putValue(attachmentObject, "id", attachmentID)
                my putValue(attachmentObject, "name", attachmentName)
                my putValue(attachmentObject, "mime_type", attachmentMIMEType)
                my putValue(attachmentObject, "file_size", attachmentFileSize)
                my putValue(attachmentObject, "downloaded", attachmentDownloaded)
                my addValue(attachmentArray, attachmentObject)
            end repeat
            my putValue(resultObject, "attachments", attachmentArray)
            return resultObject
        end tell
    end messageDictionary


    on messageSummary(aMessage, anAccount, pathItems)
        tell application "Mail"
            set resultObject to my newDictionary()
            set accountName to name of anAccount as text
            set accountID to (get id of anAccount) as text
            set localID to (get id of aMessage) as integer
            set rfcID to ""
            try
                set rfcID to (get message id of aMessage) as text
            end try
            set referenceObject to my newDictionary()
            my putValue(referenceObject, "account", accountName)
            my putValue(referenceObject, "mailbox_path", my foundationArray(pathItems))
            my putValue(referenceObject, "local_id", localID)
            my putValue(referenceObject, "rfc_message_id", rfcID)
            my putValue(referenceObject, "universal_id", "")
            my putValue(resultObject, "account", accountName)
            my putValue(resultObject, "account_id", accountID)
            my putValue(resultObject, "mailbox", my joinPath(pathItems))
            my putValue(resultObject, "mailbox_path", my foundationArray(pathItems))
            my putValue(resultObject, "message_ref", referenceObject)
            my putValue(resultObject, "sender", sender of aMessage as text)
            my putValue(resultObject, "subject", subject of aMessage as text)
            try
                my putValue(resultObject, "date_received", date received of aMessage as text)
            on error
                my putValue(resultObject, "date_received", "")
            end try
            return resultObject
        end tell
    end messageSummary


    on mailboxDictionaries(mailboxObjects, parentPath, outputArray)
        tell application "Mail"
            repeat with aMailbox in mailboxObjects
                set mailboxName to name of aMailbox as text
                set mailboxPath to parentPath & {mailboxName}
                set mailboxObject to my newDictionary()
                my putValue(mailboxObject, "name", mailboxName)
                my putValue(mailboxObject, "path", my foundationArray(mailboxPath))
                my putValue(mailboxObject, "display_path", my joinPath(mailboxPath))
                try
                    my putValue(mailboxObject, "message_count", count of messages of aMailbox)
                    my putValue(mailboxObject, "unread_count", unread count of aMailbox)
                end try
                my addValue(outputArray, mailboxObject)
                if (count of mailboxes of aMailbox) > 0 then my mailboxDictionaries(mailboxes of aMailbox, mailboxPath, outputArray)
            end repeat
        end tell
    end mailboxDictionaries


    on commandStatus()
        tell application "Mail"
            set resultObject to my newDictionary()
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", "status")
            my putValue(resultObject, "mail_version", application version as text)
            my putValue(resultObject, "message_viewer_count", count of message viewers)
            my putValue(resultObject, "outgoing_message_count", count of outgoing messages)
            set visibleOutgoingCount to 0
            repeat with outgoingMessage in outgoing messages
                try
                    if visible of outgoingMessage then set visibleOutgoingCount to visibleOutgoingCount + 1
                end try
            end repeat
            my putValue(resultObject, "visible_outgoing_message_count", visibleOutgoingCount)
            set rolesObject to my newDictionary()
            my putValue(rolesObject, "drafts", name of drafts mailbox as text)
            my putValue(rolesObject, "sent", name of sent mailbox as text)
            my putValue(rolesObject, "inbox", name of inbox as text)
            my putValue(rolesObject, "trash", name of trash mailbox as text)
            my putValue(resultObject, "role_mailboxes", rolesObject)
            return resultObject
        end tell
    end commandStatus


    on commandAccounts()
        tell application "Mail"
            set resultObject to my newDictionary()
            set accountArray to my newArray()
            repeat with anAccount in accounts
                set accountObject to my newDictionary()
                my putValue(accountObject, "name", name of anAccount as text)
                my putValue(accountObject, "id", (get id of anAccount) as text)
                my putValue(accountObject, "enabled", enabled of anAccount as boolean)
                my putValue(accountObject, "type", account type of anAccount as text)
                my putValue(accountObject, "email_addresses", my foundationArray(email addresses of anAccount))
                my addValue(accountArray, accountObject)
            end repeat
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", "accounts")
            my putValue(resultObject, "accounts", accountArray)
            return resultObject
        end tell
    end commandAccounts


    on commandMailboxes(requestObject)
        set accountQuery to my requestText(requestObject, "account", "")
        set anAccount to my resolveAccount(accountQuery)
        tell application "Mail"
            set mailboxArray to my newArray()
            my mailboxDictionaries(mailboxes of anAccount, {}, mailboxArray)
            set resultObject to my newDictionary()
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", "mailboxes")
            my putValue(resultObject, "account", name of anAccount as text)
            my putValue(resultObject, "account_id", (get id of anAccount) as text)
            my putValue(resultObject, "mailboxes", mailboxArray)
            return resultObject
        end tell
    end commandMailboxes


    on recipientContains(aMessage, recipientNeedle)
        if recipientNeedle is "" then return true
        set normalizedNeedle to my normalizedLower(recipientNeedle)
        repeat with anAddress in my allRecipientAddresses(aMessage)
            if (my normalizedLower(anAddress as text)) contains normalizedNeedle then return true
        end repeat
        return false
    end recipientContains


    on commandSearch(requestObject)
        set accountQuery to my requestText(requestObject, "account", "")
        set pathItems to my pathFromRequest(requestObject, "mailbox_path")
        set subjectFilter to my requestText(requestObject, "subject", "")
        set senderFilter to my requestText(requestObject, "sender", "")
        set recipientFilter to my requestText(requestObject, "recipient", "")
        set sinceAge to my requestInteger(requestObject, "since_age_seconds", -1)
        set beforeAge to my requestInteger(requestObject, "before_age_seconds", -1)
        set unreadOnly to my requestBoolean(requestObject, "unread", false)
        set resultLimit to my requestInteger(requestObject, "limit", 50)
        set bodyMode to my requestText(requestObject, "body_mode", "excerpt")
        set anAccount to my resolveAccount(accountQuery)
        set aMailbox to my resolveMailbox(anAccount, pathItems)
        tell application "Mail"
            if subjectFilter is not "" and senderFilter is not "" then
                set candidates to every message of aMailbox whose subject contains subjectFilter and sender contains senderFilter
            else if subjectFilter is not "" then
                set candidates to every message of aMailbox whose subject contains subjectFilter
            else if senderFilter is not "" then
                set candidates to every message of aMailbox whose sender contains senderFilter
            else
                set candidates to every message of aMailbox
            end if
            set sinceDate to missing value
            set beforeDate to missing value
            if sinceAge ≥ 0 then set sinceDate to (current date) - sinceAge
            if beforeAge ≥ 0 then set beforeDate to (current date) - beforeAge
            set messageArray to my newArray()
            repeat with aMessage in candidates
                if (messageArray's |count|() as integer) ≥ resultLimit then exit repeat
                set includeMessage to true
                if unreadOnly then
                    if read status of aMessage then set includeMessage to false
                end if
                if includeMessage and sinceDate is not missing value then
                    if date received of aMessage < sinceDate then set includeMessage to false
                end if
                if includeMessage and beforeDate is not missing value then
                    if date received of aMessage ≥ beforeDate then set includeMessage to false
                end if
                if includeMessage and not my recipientContains(aMessage, recipientFilter) then set includeMessage to false
                if includeMessage then my addValue(messageArray, my messageDictionary(aMessage, anAccount, pathItems, bodyMode, false, false))
            end repeat
            set resultObject to my newDictionary()
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", "search")
            my putValue(resultObject, "account", name of anAccount as text)
            my putValue(resultObject, "mailbox_path", my foundationArray(pathItems))
            my putValue(resultObject, "messages", messageArray)
            my putValue(resultObject, "count", messageArray's |count|() as integer)
            return resultObject
        end tell
    end commandSearch


    on isoDate(aDate)
        set formatter to current application's NSDateFormatter's alloc()'s init()
        formatter's setLocale:(current application's NSLocale's localeWithLocaleIdentifier:"en_US_POSIX")
        formatter's setDateFormat:"yyyy-MM-dd'T'HH:mm:ssXXXXX"
        return (formatter's stringFromDate:aDate) as text
    end isoDate


    on recentPrecedes(candidateItem, existingItem)
        if (item 1 of candidateItem) > (item 1 of existingItem) then return true
        if (item 1 of candidateItem) < (item 1 of existingItem) then return false
        if (item 2 of candidateItem) < (item 2 of existingItem) then return true
        if (item 2 of candidateItem) > (item 2 of existingItem) then return false
        return (item 3 of candidateItem) < (item 3 of existingItem)
    end recentPrecedes


    on insertRecent(topItems, candidateItem, resultLimit)
        set orderedItems to {}
        set inserted to false
        repeat with existingItem in topItems
            if not inserted and my recentPrecedes(candidateItem, contents of existingItem) then
                set end of orderedItems to candidateItem
                set inserted to true
            end if
            if (count of orderedItems) < resultLimit then set end of orderedItems to contents of existingItem
        end repeat
        if not inserted and (count of orderedItems) < resultLimit then set end of orderedItems to candidateItem
        return orderedItems
    end insertRecent


    on inboxCandidates(inboxMailbox, subjectFilter, senderFilter, unreadOnly, sinceDate)
        tell application "Mail"
            -- Use one selective Mail predicate, then check every filter locally.
            if subjectFilter is not "" and senderFilter is not "" and sinceDate is not missing value and unreadOnly then return every message of inboxMailbox whose subject contains subjectFilter and sender contains senderFilter and date received ≥ sinceDate and read status is false
            if subjectFilter is not "" and senderFilter is not "" and sinceDate is not missing value then return every message of inboxMailbox whose subject contains subjectFilter and sender contains senderFilter and date received ≥ sinceDate
            if subjectFilter is not "" and senderFilter is not "" and unreadOnly then return every message of inboxMailbox whose subject contains subjectFilter and sender contains senderFilter and read status is false
            if subjectFilter is not "" and senderFilter is not "" then return every message of inboxMailbox whose subject contains subjectFilter and sender contains senderFilter
            if unreadOnly then return every message of inboxMailbox whose read status is false
            if sinceDate is not missing value then return every message of inboxMailbox whose date received ≥ sinceDate
            if subjectFilter is not "" then return every message of inboxMailbox whose subject contains subjectFilter
            if senderFilter is not "" then return every message of inboxMailbox whose sender contains senderFilter
            return every message of inboxMailbox
        end tell
    end inboxCandidates


    on rankedInboxMatches(senderFilter, senderIdentity, subjectFilter, sinceEpoch, beforeEpoch, unreadOnly, resultLimit)
        tell application "Mail"
            -- Mail's aggregate inbox is the same role-backed collection shown as
            -- All Inboxes in the UI. Its children retain their real account.
            set inboxItems to mailboxes of inbox
            if (count of inboxItems) is 0 then error "No account Inboxes are available" number 9122
            set sinceDate to missing value
            set beforeDate to missing value
            if sinceEpoch ≥ 0 then set sinceDate to (current application's NSDate's dateWithTimeIntervalSince1970:sinceEpoch) as date
            if beforeEpoch ≥ 0 then set beforeDate to (current application's NSDate's dateWithTimeIntervalSince1970:beforeEpoch) as date
            set rankedItems to {}
            set matchingCount to 0
            set scannedCount to 0
            set failureArray to my newArray()
            repeat with inboxMailbox in inboxItems
                set accountName to name of inboxMailbox as text
                try
                    set anAccount to account of inboxMailbox
                    set accountName to name of anAccount as text
                    set accountID to (get id of anAccount) as text
                    set pathItems to {name of inboxMailbox as text}
                    set candidates to my inboxCandidates(inboxMailbox, subjectFilter, senderFilter, unreadOnly, sinceDate)
                    repeat with aMessage in candidates
                        set receivedDate to date received of aMessage
                        set includeMessage to true
                        if sinceDate is not missing value and receivedDate < sinceDate then set includeMessage to false
                        if beforeDate is not missing value and receivedDate ≥ beforeDate then set includeMessage to false
                        if includeMessage and senderFilter is not "" then
                            if (my normalizedLower(sender of aMessage as text)) does not contain (my normalizedLower(senderFilter)) then set includeMessage to false
                        end if
                        if includeMessage and senderIdentity is not "" then
                            if not my identityMatches(sender of aMessage as text, senderIdentity) then set includeMessage to false
                        end if
                        if includeMessage and subjectFilter is not "" then
                            if (my normalizedLower(subject of aMessage as text)) does not contain (my normalizedLower(subjectFilter)) then set includeMessage to false
                        end if
                        if includeMessage and unreadOnly then
                            -- An unavailable read status cannot establish an unread match.
                            if read status of aMessage then set includeMessage to false
                        end if
                        if includeMessage then
                            set localID to (get id of aMessage) as integer
                            set matchingCount to matchingCount + 1
                            set candidateItem to {receivedDate, accountID, localID, anAccount, pathItems, aMessage}
                            set rankedItems to my insertRecent(rankedItems, candidateItem, resultLimit)
                        end if
                    end repeat
                    set scannedCount to scannedCount + 1
                on error errorMessage number errorNumber
                    set failureObject to my newDictionary()
                    my putValue(failureObject, "account", accountName)
                    my putValue(failureObject, "code", "MAIL_APPLESCRIPT_" & errorNumber)
                    my putValue(failureObject, "error", errorMessage)
                    my addValue(failureArray, failureObject)
                end try
            end repeat
            return {rankedItems, matchingCount, scannedCount, count of inboxItems, failureArray}
        end tell
    end rankedInboxMatches


    on rankedMessages(rankedItems, bodyMode, includeHeaders, includeSource, failureArray)
        set messageArray to my newArray()
        repeat with rankedItem in rankedItems
            set aMessage to item 6 of rankedItem
            set anAccount to item 4 of rankedItem
            set pathItems to item 5 of rankedItem
            try
                set messageRecord to my messageDictionary(aMessage, anAccount, pathItems, bodyMode, includeHeaders, includeSource)
                if (my requestValue(messageRecord, "read")) is missing value then error "Cannot verify message read status" number 9125
            on error errorMessage number errorNumber
                set failureObject to my newDictionary()
                my putValue(failureObject, "account", name of anAccount as text)
                my putValue(failureObject, "local_id", item 3 of rankedItem)
                my putValue(failureObject, "code", "MAIL_APPLESCRIPT_" & errorNumber)
                my putValue(failureObject, "error", errorMessage)
                my addValue(failureArray, failureObject)
                try
                    set messageRecord to my messageDictionary(aMessage, anAccount, pathItems, "none", false, false)
                on error
                    set messageRecord to missing value
                end try
            end try
            if messageRecord is not missing value then
                my putValue(messageRecord, "date_received_iso", my isoDate(item 1 of rankedItem))
                my addValue(messageArray, messageRecord)
            end if
        end repeat
        return messageArray
    end rankedMessages


    on commandRecent(requestObject)
        set resultLimit to my requestInteger(requestObject, "limit", 3)
        set bodyMode to my requestText(requestObject, "body_mode", "excerpt")
        set unreadOnly to my requestBoolean(requestObject, "unread", false)
        set senderFilter to my requestText(requestObject, "sender", "")
        set subjectFilter to my requestText(requestObject, "subject", "")
        set sinceEpoch to my requestReal(requestObject, "since_epoch_seconds", -1)
        set beforeEpoch to my requestReal(requestObject, "before_epoch_seconds", -1)
        if resultLimit < 1 or resultLimit > 200 then error "Recent limit must be between 1 and 200" number 9121
        set searchAge to -1
        if unreadOnly or senderFilter is not "" or subjectFilter is not "" or sinceEpoch ≥ 0 or beforeEpoch ≥ 0 then
            set {topItems, matchingCount, scannedCount, accountCount, failureArray} to my rankedInboxMatches(senderFilter, "", subjectFilter, sinceEpoch, beforeEpoch, unreadOnly, resultLimit)
        else
            repeat with ageValue in {604800, 2592000, 31536000, -1}
                set searchAge to ageValue as integer
                set searchEpoch to -1
                if searchAge ≥ 0 then
                    set nowObject to current application's NSDate's |date|()
                    set searchEpoch to (nowObject's timeIntervalSince1970() as real) - searchAge
                end if
                set {topItems, matchingCount, scannedCount, accountCount, failureArray} to my rankedInboxMatches("", "", "", searchEpoch, -1, false, resultLimit)
                if (count of topItems) ≥ resultLimit or (failureArray's |count|() as integer) > 0 then exit repeat
            end repeat
        end if
        set messageArray to my rankedMessages(topItems, bodyMode, false, false, failureArray)
        set isComplete to (failureArray's |count|() as integer) is 0
        set resultObject to my newDictionary()
        my putValue(resultObject, "ok", isComplete)
        my putValue(resultObject, "operation", "recent")
        my putValue(resultObject, "scope", "all-inboxes")
        my putValue(resultObject, "complete", isComplete)
        my putValue(resultObject, "accounts_scanned", scannedCount)
        my putValue(resultObject, "accounts_total", accountCount)
        my putValue(resultObject, "search_age_seconds", searchAge)
        my putValue(resultObject, "count", messageArray's |count|() as integer)
        my putValue(resultObject, "messages", messageArray)
        my putValue(resultObject, "failures", failureArray)
        if unreadOnly then
            if isComplete then
                my putValue(resultObject, "unread_total", matchingCount)
            else
                my putValue(resultObject, "unread_verified_count", matchingCount)
            end if
        end if
        return resultObject
    end commandRecent


    on fastMatchingMessages(aMailbox, subjectFilter, senderIdentity, recipientFilter, sinceAge, beforeAge, unreadOnly, resultLimit)
        tell application "Mail"
            set senderToken to my firstIdentityToken(senderIdentity)
            if subjectFilter is not "" and senderToken is not "" then
                set candidates to every message of aMailbox whose subject contains subjectFilter and sender contains senderToken
            else if subjectFilter is not "" then
                set candidates to every message of aMailbox whose subject contains subjectFilter
            else if senderToken is not "" then
                set candidates to every message of aMailbox whose sender contains senderToken
            else
                set candidates to every message of aMailbox
            end if
            set sinceDate to missing value
            set beforeDate to missing value
            if sinceAge ≥ 0 then set sinceDate to (current date) - sinceAge
            if beforeAge ≥ 0 then set beforeDate to (current date) - beforeAge
            set matches to {}
            repeat with aMessage in candidates
                if (count of matches) ≥ resultLimit then exit repeat
                set includeMessage to true
                if senderIdentity is not "" and not my identityMatches(sender of aMessage as text, senderIdentity) then set includeMessage to false
                if includeMessage and unreadOnly then
                    if read status of aMessage then set includeMessage to false
                end if
                if includeMessage and sinceDate is not missing value then
                    if date received of aMessage < sinceDate then set includeMessage to false
                end if
                if includeMessage and beforeDate is not missing value then
                    if date received of aMessage ≥ beforeDate then set includeMessage to false
                end if
                if includeMessage and not my recipientContains(aMessage, recipientFilter) then set includeMessage to false
                if includeMessage then set end of matches to aMessage
            end repeat
            return matches
        end tell
    end fastMatchingMessages


    on commandLocate(requestObject)
        set senderIdentity to my requestText(requestObject, "sender_identity", "")
        set subjectFilter to my requestText(requestObject, "subject", "")
        set sinceEpoch to my requestReal(requestObject, "since_epoch_seconds", -1)
        set beforeEpoch to my requestReal(requestObject, "before_epoch_seconds", -1)
        set resultLimit to my requestInteger(requestObject, "limit", 50)
        set readIfUnique to my requestBoolean(requestObject, "read_if_unique", false)
        if readIfUnique and resultLimit < 2 then set resultLimit to 2
        set bodyMode to my requestText(requestObject, "body_mode", "excerpt")
        set includeHeaders to my requestBoolean(requestObject, "include_headers", false)
        set includeSource to my requestBoolean(requestObject, "include_source", false)
        if senderIdentity is "" then error "A sender identity is required for cross-account INBOX lookup" number 9120
        set senderToken to my firstIdentityToken(senderIdentity)
        set {rankedItems, matchingCount, scannedCount, accountCount, failureArray} to my rankedInboxMatches(senderToken, senderIdentity, subjectFilter, sinceEpoch, beforeEpoch, false, resultLimit)
        set isComplete to (failureArray's |count|() as integer) is 0
        set resultObject to my newDictionary()
        my putValue(resultObject, "operation", "locate")
        my putValue(resultObject, "scope", "all-inboxes")
        my putValue(resultObject, "accounts_scanned", scannedCount)
        my putValue(resultObject, "accounts_total", accountCount)
        my putValue(resultObject, "sender_identity", senderIdentity)
        my putValue(resultObject, "count", count of rankedItems)
        if isComplete then
            my putValue(resultObject, "match_total", matchingCount)
        else
            my putValue(resultObject, "match_verified_count", matchingCount)
        end if
        my putValue(resultObject, "read_if_unique", readIfUnique)
        if readIfUnique and matchingCount is 1 and isComplete then
            set messageArray to my rankedMessages(rankedItems, bodyMode, includeHeaders, includeSource, failureArray)
            if (messageArray's |count|() as integer) is 1 and (failureArray's |count|() as integer) is 0 then
                my putValue(resultObject, "message", messageArray's objectAtIndex:0)
                my putValue(resultObject, "unique_read", true)
            else
                set isComplete to false
                my putValue(resultObject, "messages", messageArray)
                my putValue(resultObject, "unique_read", false)
            end if
        else
            set messageArray to my newArray()
            repeat with rankedItem in rankedItems
                try
                    set messageRecord to my messageSummary(item 6 of rankedItem, item 4 of rankedItem, item 5 of rankedItem)
                    my putValue(messageRecord, "date_received_iso", my isoDate(item 1 of rankedItem))
                    my addValue(messageArray, messageRecord)
                on error errorMessage number errorNumber
                    set isComplete to false
                    set failureObject to my newDictionary()
                    my putValue(failureObject, "account", name of item 4 of rankedItem as text)
                    my putValue(failureObject, "code", "MAIL_APPLESCRIPT_" & errorNumber)
                    my putValue(failureObject, "error", errorMessage)
                    my addValue(failureArray, failureObject)
                end try
            end repeat
            my putValue(resultObject, "messages", messageArray)
            my putValue(resultObject, "unique_read", false)
        end if
        my putValue(resultObject, "ok", isComplete)
        my putValue(resultObject, "complete", isComplete)
        my putValue(resultObject, "failures", failureArray)
        return resultObject
    end commandLocate


    on commandInspect(requestObject)
        set accountQuery to my requestText(requestObject, "account", "")
        set pathItems to my pathFromRequest(requestObject, "mailbox_path")
        set subjectFilter to my requestText(requestObject, "subject", "")
        set senderIdentity to my requestText(requestObject, "sender_identity", "")
        set recipientFilter to my requestText(requestObject, "recipient", "")
        set sinceAge to my requestInteger(requestObject, "since_age_seconds", -1)
        set beforeAge to my requestInteger(requestObject, "before_age_seconds", -1)
        set unreadOnly to my requestBoolean(requestObject, "unread", false)
        set resultLimit to my requestInteger(requestObject, "limit", 50)
        set readIfUnique to my requestBoolean(requestObject, "read_if_unique", false)
        if readIfUnique and resultLimit < 2 then set resultLimit to 2
        set bodyMode to my requestText(requestObject, "body_mode", "excerpt")
        set includeHeaders to my requestBoolean(requestObject, "include_headers", false)
        set includeSource to my requestBoolean(requestObject, "include_source", false)
        set anAccount to my resolveAccount(accountQuery)
        set aMailbox to my resolveMailbox(anAccount, pathItems)
        set matches to my fastMatchingMessages(aMailbox, subjectFilter, senderIdentity, recipientFilter, sinceAge, beforeAge, unreadOnly, resultLimit)
        tell application "Mail"
            set resultObject to my newDictionary()
            set candidateCount to count of matches
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", "inspect")
            my putValue(resultObject, "account", name of anAccount as text)
            my putValue(resultObject, "mailbox_path", my foundationArray(pathItems))
            my putValue(resultObject, "count", candidateCount)
            my putValue(resultObject, "read_if_unique", readIfUnique)
            if readIfUnique and candidateCount is 1 then
                my putValue(resultObject, "message", my messageDictionary(item 1 of matches, anAccount, pathItems, bodyMode, includeHeaders, includeSource))
                my putValue(resultObject, "unique_read", true)
            else
                set messageArray to my newArray()
                repeat with aMessage in matches
                    my addValue(messageArray, my messageSummary(aMessage, anAccount, pathItems))
                end repeat
                my putValue(resultObject, "messages", messageArray)
                my putValue(resultObject, "message", missing value)
                my putValue(resultObject, "unique_read", false)
            end if
            return resultObject
        end tell
    end commandInspect


    on commandRead(requestObject)
        set referenceObject to my requestValue(requestObject, "message_ref")
        set bodyMode to my requestText(requestObject, "body_mode", "excerpt")
        set includeHeaders to my requestBoolean(requestObject, "include_headers", false)
        set includeSource to my requestBoolean(requestObject, "include_source", false)
        set {anAccount, aMailbox, aMessage, pathItems} to my findMessage(referenceObject)
        set resultObject to my newDictionary()
        my putValue(resultObject, "ok", true)
        my putValue(resultObject, "operation", "read")
        my putValue(resultObject, "message", my messageDictionary(aMessage, anAccount, pathItems, bodyMode, includeHeaders, includeSource))
        return resultObject
    end commandRead


    on commandReadRoleMessage(requestObject)
        set roleName to my requestText(requestObject, "role", "")
        set referenceObject to my requestValue(requestObject, "message_ref")
        set bodyMode to my requestText(requestObject, "body_mode", "excerpt")
        set {anAccount, aRoleMailbox, aMessage, pathItems} to my findRoleMessage(roleName, referenceObject)
        set resultObject to my newDictionary()
        my putValue(resultObject, "ok", true)
        my putValue(resultObject, "operation", "read-role-message")
        my putValue(resultObject, "role", roleName)
        my putValue(resultObject, "message", my messageDictionary(aMessage, anAccount, pathItems, bodyMode, false, false))
        return resultObject
    end commandReadRoleMessage


    on matchesEnvelope(aMessage, senderText, subjectText, toAddresses)
        tell application "Mail"
            try
                if my canonicalAddress(sender of aMessage as text) is not my canonicalAddress(senderText) then return false
                if (subject of aMessage as text) is not subjectText then return false
                if not my sameAddressList(my recipientAddresses(aMessage, "to"), toAddresses) then return false
                return true
            on error
                return false
            end try
        end tell
    end matchesEnvelope


    on matchingRoleMessages(roleName, senderText, subjectText, toAddresses)
        set aRoleMailbox to my roleMailbox(roleName)
        tell application "Mail"
            set candidates to every message of aRoleMailbox whose subject is subjectText
            set matches to {}
            repeat with aMessage in candidates
                if my matchesEnvelope(aMessage, senderText, subjectText, toAddresses) then set end of matches to aMessage
            end repeat
            return matches
        end tell
    end matchingRoleMessages


    on commandCountSent(requestObject)
        set senderText to my requestText(requestObject, "sender", "")
        set subjectText to my requestText(requestObject, "subject", "")
        set toAddresses to my requestTextList(requestObject, "to")
        set matches to my matchingRoleMessages("sent", senderText, subjectText, toAddresses)
        set resultObject to my newDictionary()
        my putValue(resultObject, "ok", true)
        my putValue(resultObject, "operation", "count-sent")
        my putValue(resultObject, "count", count of matches)
        return resultObject
    end commandCountSent


    on messageIDs(messageObjects)
        set resultIDs to {}
        tell application "Mail"
            repeat with aMessage in messageObjects
                try
                    set end of resultIDs to (get id of aMessage) as integer
                end try
            end repeat
        end tell
        return resultIDs
    end messageIDs


    on addRecipients(outgoingMessage, toAddresses, ccAddresses, bccAddresses)
        tell application "Mail"
            tell outgoingMessage
                repeat with anAddress in toAddresses
                    make new to recipient at end of to recipients with properties {address:anAddress as text}
                end repeat
                repeat with anAddress in ccAddresses
                    make new cc recipient at end of cc recipients with properties {address:anAddress as text}
                end repeat
                repeat with anAddress in bccAddresses
                    make new bcc recipient at end of bcc recipients with properties {address:anAddress as text}
                end repeat
            end tell
        end tell
    end addRecipients


    on addAttachments(outgoingMessage, attachmentPaths)
        repeat with aPath in attachmentPaths
            set attachmentFile to (POSIX file (aPath as text)) as alias
            tell application "Mail"
                make new attachment with properties {file name:attachmentFile} at after last paragraph of content of outgoingMessage
            end tell
        end repeat
    end addAttachments


    on replaceRecipients(outgoingMessage, toAddresses, ccAddresses, bccAddresses)
        tell application "Mail"
            tell outgoingMessage
                try
                    delete every to recipient
                end try
                try
                    delete every cc recipient
                end try
                try
                    delete every bcc recipient
                end try
            end tell
        end tell
        my addRecipients(outgoingMessage, toAddresses, ccAddresses, bccAddresses)
    end replaceRecipients


    on waitForNewDraft(anAccount, senderText, subjectText, toAddresses, beforeIDs, attemptLimit, pollDelay)
        set draftsRole to my roleMailbox("drafts")
        tell application "Mail"
            repeat with attempt from 1 to attemptLimit
                delay pollDelay
                set candidates to every message of draftsRole whose subject is subjectText
                set newMatches to {}
                repeat with aMessage in candidates
                    try
                        if beforeIDs does not contain ((get id of aMessage) as integer) and my matchesEnvelope(aMessage, senderText, subjectText, toAddresses) then set end of newMatches to aMessage
                    end try
                end repeat
                if (count of newMatches) is 1 then return item 1 of newMatches
                if (count of newMatches) > 1 then error "More than one new matching draft appeared" number 9201
            end repeat
            error "Timed out waiting for the saved Mail draft" number 9202
        end tell
    end waitForNewDraft


    on draftResponse(aDraft, anAccount, operationName, outgoingID)
        tell application "Mail"
            set pathItems to {name of mailbox of aDraft as text}
            set senderText to sender of aDraft as text
            set subjectText to subject of aDraft as text
            set toAddresses to my recipientAddresses(aDraft, "to")
            set sentMatches to my matchingRoleMessages("sent", senderText, subjectText, toAddresses)
            set resultObject to my newDictionary()
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", operationName)
            my putValue(resultObject, "draft", my messageDictionary(aDraft, anAccount, pathItems, "full", false, false))
            my putValue(resultObject, "sent_before", count of sentMatches)
            if outgoingID > 0 then my putValue(resultObject, "draft_outgoing_id", outgoingID)
            return resultObject
        end tell
    end draftResponse


    on commandDraftNew(requestObject)
        set accountQuery to my requestText(requestObject, "account", "")
        set senderText to my requestText(requestObject, "from", "")
        set toAddresses to my requestTextList(requestObject, "to")
        set ccAddresses to my requestTextList(requestObject, "cc")
        set bccAddresses to my requestTextList(requestObject, "bcc")
        set subjectText to my requestText(requestObject, "subject", "")
        set bodyText to my requestText(requestObject, "body", "")
        set attachmentPaths to my requestTextList(requestObject, "attachments")
        set attemptLimit to my requestInteger(requestObject, "draft_verification_attempts", 1)
        set pollDelay to my requestInteger(requestObject, "poll_interval_seconds", 1)
        set anAccount to my resolveAccount(accountQuery)
        tell application "Mail"
            if email addresses of anAccount does not contain senderText then error "Sender is not configured on the selected account" number 9203
            set existingDrafts to my matchingRoleMessages("drafts", senderText, subjectText, toAddresses)
            if (count of existingDrafts) > 0 then error "A matching draft already exists; use a unique subject" number 9214
            set draftsRole to my roleMailbox("drafts")
            set beforeIDs to my messageIDs(every message of draftsRole whose subject is subjectText)
            set outgoingMessage to make new outgoing message with properties {visible:false, sender:senderText, subject:subjectText, content:bodyText & return}
            set outgoingID to (get id of outgoingMessage) as integer
            my addRecipients(outgoingMessage, toAddresses, ccAddresses, bccAddresses)
            my addAttachments(outgoingMessage, attachmentPaths)
            save outgoingMessage
            set aDraft to my waitForNewDraft(anAccount, senderText, subjectText, toAddresses, beforeIDs, attemptLimit, pollDelay)
            return my draftResponse(aDraft, anAccount, "draft-new", outgoingID)
        end tell
    end commandDraftNew


    on commandDraftReply(requestObject)
        set referenceObject to my requestValue(requestObject, "message_ref")
        set bodyText to my requestText(requestObject, "body", "")
        set replyAll to my requestBoolean(requestObject, "reply_all", false)
        set attachmentPaths to my requestTextList(requestObject, "attachments")
        set attemptLimit to my requestInteger(requestObject, "draft_verification_attempts", 1)
        set pollDelay to my requestInteger(requestObject, "poll_interval_seconds", 1)
        set {anAccount, aMailbox, sourceMessage, sourcePath} to my findMessage(referenceObject)
        tell application "Mail"
            set sourceBody to content of sourceMessage as text
            if (length of sourceBody) < 1 then error "Reply source body is empty" number 9204
            set draftsRole to my roleMailbox("drafts")
            set beforeIDs to my messageIDs(every message of draftsRole)
            set outgoingMessage to reply sourceMessage opening window false reply to all replyAll
            set outgoingID to (get id of outgoingMessage) as integer
            if (count of to recipients of outgoingMessage) is 0 and (count of cc recipients of outgoingMessage) is 0 then error "Mail generated a reply without a recipient" number 9205
            set senderText to sender of outgoingMessage as text
            set subjectText to subject of outgoingMessage as text
            set toAddresses to my recipientAddresses(outgoingMessage, "to")
            set content of outgoingMessage to bodyText & return & return & sourceBody
            my addAttachments(outgoingMessage, attachmentPaths)
            save outgoingMessage
            set aDraft to my waitForNewDraft(anAccount, senderText, subjectText, toAddresses, beforeIDs, attemptLimit, pollDelay)
            set persistedBody to content of aDraft as text
            set normalizedPersistedBody to my normalizedContentText(persistedBody)
            if normalizedPersistedBody does not contain my normalizedContentText(bodyText) or normalizedPersistedBody does not contain my normalizedContentText(sourceBody) then error "Reply draft did not preserve the body and source context" number 9204
            return my draftResponse(aDraft, anAccount, "draft-reply", outgoingID)
        end tell
    end commandDraftReply


    on commandDraftForward(requestObject)
        set referenceObject to my requestValue(requestObject, "message_ref")
        set bodyText to my requestText(requestObject, "body", "")
        set toAddresses to my requestTextList(requestObject, "to")
        set ccAddresses to my requestTextList(requestObject, "cc")
        set bccAddresses to my requestTextList(requestObject, "bcc")
        set attachmentPaths to my requestTextList(requestObject, "attachments")
        set attemptLimit to my requestInteger(requestObject, "draft_verification_attempts", 1)
        set pollDelay to my requestInteger(requestObject, "poll_interval_seconds", 1)
        set {anAccount, aMailbox, sourceMessage, sourcePath} to my findMessage(referenceObject)
        tell application "Mail"
            set sourceBody to content of sourceMessage as text
            if (length of sourceBody) < 1 then error "Forward source body is empty" number 9205
            set draftsRole to my roleMailbox("drafts")
            set beforeIDs to my messageIDs(every message of draftsRole)
            set outgoingMessage to forward sourceMessage opening window false
            set outgoingID to (get id of outgoingMessage) as integer
            set senderText to sender of outgoingMessage as text
            set subjectText to subject of outgoingMessage as text
            set content of outgoingMessage to bodyText & return & return & sourceBody
            my replaceRecipients(outgoingMessage, toAddresses, ccAddresses, bccAddresses)
            my addAttachments(outgoingMessage, attachmentPaths)
            save outgoingMessage
            set aDraft to my waitForNewDraft(anAccount, senderText, subjectText, toAddresses, beforeIDs, attemptLimit, pollDelay)
            set persistedBody to content of aDraft as text
            set normalizedPersistedBody to my normalizedContentText(persistedBody)
            if normalizedPersistedBody does not contain my normalizedContentText(bodyText) or normalizedPersistedBody does not contain my normalizedContentText(sourceBody) then error "Forward draft did not preserve the body and source context" number 9205
            return my draftResponse(aDraft, anAccount, "draft-forward", outgoingID)
        end tell
    end commandDraftForward


    on messageMatchesReferenceParts(aMessage, localID, expectedRFCID, expectedUniversalID)
        tell application "Mail"
            try
                if ((get id of aMessage) as integer) is localID then return true
            end try
            if expectedRFCID is not "" then
                try
                    if ((get message id of aMessage) as text) is expectedRFCID then return true
                end try
            end if
            if expectedUniversalID is not "" and my messageMatchesUniversalID(aMessage, expectedUniversalID) then return true
            return false
        end tell
    end messageMatchesReferenceParts


    on boundDraftCandidates(aDraftsMailbox, senderText, subjectText, toAddresses, draftParts, sentParts)
        set {draftAccount, draftPath, draftLocalID, draftRFCID, draftUniversalID} to draftParts
        set {sentAccount, sentPath, sentLocalID, sentRFCID, sentUniversalID} to sentParts
        tell application "Mail"
            set candidates to every message of aDraftsMailbox whose subject is subjectText
            set matches to {}
            repeat with candidateMessage in candidates
                if my matchesEnvelope(candidateMessage, senderText, subjectText, toAddresses) then
                    if my messageMatchesReferenceParts(candidateMessage, draftLocalID, draftRFCID, draftUniversalID) or my messageMatchesReferenceParts(candidateMessage, sentLocalID, sentRFCID, sentUniversalID) then set end of matches to candidateMessage
                end if
            end repeat
            return matches
        end tell
    end boundDraftCandidates


    on senderBelongsToAccount(senderText, anAccount)
        tell application "Mail" to set configuredAddresses to email addresses of anAccount
        repeat with configuredAddress in configuredAddresses
            if my canonicalAddress(configuredAddress as text) is my canonicalAddress(senderText) then return true
        end repeat
        return false
    end senderBelongsToAccount


    on outgoingDictionary(outgoingMessage)
        tell application "Mail"
            set resultObject to my newDictionary()
            my putValue(resultObject, "id", (get id of outgoingMessage) as integer)
            my putValue(resultObject, "sender", sender of outgoingMessage as text)
            my putValue(resultObject, "subject", subject of outgoingMessage as text)
            my putValue(resultObject, "to", my foundationArray(my recipientAddresses(outgoingMessage, "to")))
            my putValue(resultObject, "cc", my foundationArray(my recipientAddresses(outgoingMessage, "cc")))
            my putValue(resultObject, "bcc", my foundationArray(my recipientAddresses(outgoingMessage, "bcc")))
            my putValue(resultObject, "visible", visible of outgoingMessage as boolean)
            return resultObject
        end tell
    end outgoingDictionary


    on matchingOutgoingByIDs(outgoingIDs, senderText, subjectText, toAddresses)
        tell application "Mail"
            set matches to {}
            repeat with outgoingMessage in outgoing messages
                set outgoingID to (get id of outgoingMessage) as integer
                if outgoingIDs contains outgoingID then
                    if not my matchesEnvelope(outgoingMessage, senderText, subjectText, toAddresses) then error "Bound outgoing message envelope changed" number 9218
                    set end of matches to outgoingMessage
                end if
            end repeat
            return matches
        end tell
    end matchingOutgoingByIDs


    on commandOutgoingStatus(requestObject)
        set accountQuery to my requestText(requestObject, "account", "")
        set subjectContains to my requestText(requestObject, "subject_contains", "")
        set anAccount to my resolveAccount(accountQuery)
        set outputArray to my newArray()
        tell application "Mail"
            repeat with outgoingMessage in outgoing messages
                set senderText to sender of outgoingMessage as text
                set subjectText to subject of outgoingMessage as text
                if my senderBelongsToAccount(senderText, anAccount) and (subjectContains is "" or subjectText contains subjectContains) then my addValue(outputArray, my outgoingDictionary(outgoingMessage))
            end repeat
        end tell
        set resultObject to my newDictionary()
        my putValue(resultObject, "ok", true)
        my putValue(resultObject, "operation", "outgoing-status")
        my putValue(resultObject, "account", accountQuery)
        my putValue(resultObject, "count", outputArray's |count|() as integer)
        set visibleCount to 0
        repeat with outputItem in outputArray
            if (outputItem's objectForKey:"visible") as boolean then set visibleCount to visibleCount + 1
        end repeat
        my putValue(resultObject, "visible_count", visibleCount)
        my putValue(resultObject, "outgoing_messages", outputArray)
        return resultObject
    end commandOutgoingStatus


    on commandSendPlan(requestObject)
        set operationName to my requestText(requestObject, "operation", "")
        set accountQuery to my requestText(requestObject, "account", "")
        set senderText to my requestText(requestObject, "from", "")
        set toAddresses to my requestTextList(requestObject, "to")
        set ccAddresses to my requestTextList(requestObject, "cc")
        set bccAddresses to my requestTextList(requestObject, "bcc")
        set subjectText to my requestText(requestObject, "subject", "")
        set bodyText to my requestText(requestObject, "body", "")
        set sourceReference to my requestValue(requestObject, "source_ref")
        set replyAll to my requestBoolean(requestObject, "reply_all", false)
        set draftReference to my requestValue(requestObject, "draft_ref")
        set expectedOutgoingID to my requestInteger(requestObject, "outgoing_id", -1)
        set expectedSentBefore to my requestInteger(requestObject, "sent_before", -1)
        set attachmentPaths to my requestTextList(requestObject, "attachments")
        set attemptLimit to my requestInteger(requestObject, "send_verification_attempts", 1)
        set pollDelay to my requestInteger(requestObject, "poll_interval_seconds", 1)

        set anAccount to my resolveAccount(accountQuery)
        tell application "Mail"
            set configuredAddresses to email addresses of anAccount
        end tell
        set configuredSender to false
        repeat with configuredAddress in configuredAddresses
            if my canonicalAddress(configuredAddress as text) is my canonicalAddress(senderText) then set configuredSender to true
        end repeat
        if not configuredSender then error "Sender is not configured on the selected account" number 9203
        set beforeMatches to my matchingRoleMessages("sent", senderText, subjectText, toAddresses)
        if (count of beforeMatches) is not expectedSentBefore then error "Sent baseline changed after preparation" number 9209
        set beforeIDs to my messageIDs(beforeMatches)

        if expectedOutgoingID < 1 then error "Prepared outgoing message id is missing" number 9221
        set outgoingMatches to my matchingOutgoingByIDs({expectedOutgoingID}, senderText, subjectText, toAddresses)
        if (count of outgoingMatches) is not 1 then error "Prepared outgoing message is unavailable" number 9221
        set outgoingMessage to item 1 of outgoingMatches
        tell application "Mail"
            if not my sameAddressList(my recipientAddresses(outgoingMessage, "cc"), ccAddresses) then error "Prepared outgoing Cc changed" number 9222
            if not my sameAddressList(my recipientAddresses(outgoingMessage, "bcc"), bccAddresses) then error "Prepared outgoing Bcc changed" number 9222
            if my normalizedContentText(content of outgoingMessage as text) is not my normalizedContentText(bodyText) then error "Prepared outgoing body changed" number 9222
        end tell

        -- Mail's visible composer send transition clears the saved server draft.
        -- Sending this object while hidden left the draft in Gmail Drafts.
        tell application "Mail"
            set visible of outgoingMessage to true
            set visibleAttachmentCount to count of attachments of content of outgoingMessage
            if visibleAttachmentCount is 0 and (count of attachmentPaths) > 0 then my addAttachments(outgoingMessage, attachmentPaths)
            if (count of attachments of content of outgoingMessage) is not (count of attachmentPaths) then error "Prepared outgoing attachments changed" number 9223
            set sendAccepted to send outgoingMessage
            if not sendAccepted then error "Mail did not accept the outgoing message" number 9210
            set sentMessage to missing value
            repeat with attempt from 1 to attemptLimit
                delay pollDelay
                set currentMatches to my matchingRoleMessages("sent", senderText, subjectText, toAddresses)
                set newMatches to {}
                repeat with candidateMessage in currentMatches
                    if beforeIDs does not contain ((get id of candidateMessage) as integer) then set end of newMatches to candidateMessage
                end repeat
                if (count of newMatches) is 1 then
                    set sentMessage to item 1 of newMatches
                    exit repeat
                end if
                if (count of newMatches) > 1 then error "Duplicate Sent copies detected" number 9211
            end repeat
            if sentMessage is missing value then error "Sent verification timed out; do not retry automatically" number 9212
            if (length of (content of sentMessage as text)) < 3 then error "Sent copy body is empty" number 9213
            if (count of attachmentPaths) > 0 then
                set sentAttachmentNames to {}
                repeat with sentAttachment in mail attachments of sentMessage
                    set end of sentAttachmentNames to name of sentAttachment as text
                end repeat
                repeat with expectedPath in attachmentPaths
                    set expectedName to ((current application's NSString's stringWithString:(expectedPath as text))'s lastPathComponent()) as text
                    if sentAttachmentNames does not contain expectedName then error "Sent copy is missing an approved attachment" number 9215
                end repeat
            end if
            set replyHeaderVerified to missing value
            if operationName is "reply" and sourceReference is not missing value then
                set {sourceAccount, sourceMailbox, sourceMessage, sourcePath} to my findMessage(sourceReference)
                set sourceRFCID to ""
                try
                    set sourceRFCID to (get message id of sourceMessage) as text
                end try
                if sourceRFCID is not "" then
                    try
                        set replyHeaderVerified to (all headers of sentMessage as text) contains sourceRFCID
                    end try
                end if
            end if
            set sentPath to {name of mailbox of sentMessage as text}
            set sentDictionary to my messageDictionary(sentMessage, anAccount, sentPath, "full", false, false)
            set draftRemaining to missing value
            try
                set draftParts to my refParts(draftReference)
                set sentParts to my refParts(my requestValue(sentDictionary, "message_ref"))
                set {draftAccount, draftPath, draftLocalID, draftRFCID, draftUniversalID} to draftParts
                set aDraftsMailbox to my resolveMailbox(anAccount, draftPath)
                set draftRemaining to ((count of my boundDraftCandidates(aDraftsMailbox, senderText, subjectText, toAddresses, draftParts, sentParts)) > 0)
            end try
            set resultObject to my newDictionary()
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", "send-plan")
            my putValue(resultObject, "send_accepted", sendAccepted)
            my putValue(resultObject, "sent_verified", true)
            my putValue(resultObject, "sent_delta", 1)
            my putValue(resultObject, "reply_header_verified", replyHeaderVerified)
            my putValue(resultObject, "sent", sentDictionary)
            my putValue(resultObject, "send_outgoing_id", expectedOutgoingID)
            my putValue(resultObject, "draft_remaining", draftRemaining)
            return resultObject
        end tell
    end commandSendPlan


    on findAttachment(aMessage, attachmentID)
        tell application "Mail"
            set matches to {}
            repeat with anAttachment in mail attachments of aMessage
                if ((get id of anAttachment) as text) is attachmentID then set end of matches to anAttachment
            end repeat
            if (count of matches) is not 1 then error "Expected one attachment; found " & (count of matches) number 9301
            return item 1 of matches
        end tell
    end findAttachment


    on commandAct(requestObject)
        set referenceArray to my requestValue(requestObject, "refs")
        if referenceArray is missing value then error "A refs array is required" number 9310
        set referenceCount to referenceArray's |count|() as integer
        if referenceCount < 1 or referenceCount > 200 then error "Act requires 1 to 200 message refs" number 9311
        set actionNames to my requestTextList(requestObject, "actions")
        if actionNames is not {"mark-read"} and actionNames is not {"trash"} and actionNames is not {"mark-read", "trash"} then error "Supported actions are mark-read, trash, or mark-read,trash" number 9312
        set willRead to actionNames contains "mark-read"
        set willTrash to actionNames contains "trash"
        set attemptLimit to my requestInteger(requestObject, "action_verification_attempts", 6)
        set pollDelay to my requestInteger(requestObject, "poll_interval_seconds", 1)
        tell application "Mail"
            if willTrash then set aggregateTrash to my roleMailbox("trash")
            set preparedItems to {}
            set targetKeys to {}
            repeat with referenceIndex from 0 to (referenceCount - 1)
                set referenceObject to referenceArray's objectAtIndex:referenceIndex
                set {anAccount, sourceMailbox, aMessage, sourcePath} to my findMessage(referenceObject)
                set localID to (get id of aMessage) as integer
                set accountID to (get id of anAccount) as text
                set targetKey to accountID & ":" & (my joinPath(sourcePath)) & ":" & localID
                if targetKeys contains targetKey then error "Duplicate message target" number 9313
                set end of targetKeys to targetKey
                set sourceSubject to subject of aMessage as text
                set sourceRFCID to ""
                try
                    set sourceRFCID to (get message id of aMessage) as text
                end try
                if willTrash then
                    if sourceRFCID is "" then error "Trash verification requires an RFC Message-ID" number 9314
                    set deleteMovesToTrash to false
                    try
                        set deleteMovesToTrash to move deleted messages to trash of anAccount as boolean
                    end try
                    if deleteMovesToTrash then
                        set explicitTrash to missing value
                    else
                        set explicitTrash to my accountTrashMailbox(aggregateTrash, anAccount)
                    end if
                    set preexistingCandidates to every message of aggregateTrash whose subject is sourceSubject
                    repeat with existingMessage in preexistingCandidates
                        try
                            if ((get id of account of mailbox of existingMessage) as text) is accountID and ((get message id of existingMessage) as text) is sourceRFCID then error "A matching message already exists in this account's Trash" number 9316
                        on error errorMessage number errorNumber
                            if errorNumber is 9316 then error errorMessage number errorNumber
                        end try
                    end repeat
                end if
                if not willTrash then set explicitTrash to missing value
                set end of preparedItems to {referenceObject, anAccount, aMessage, sourcePath, localID, sourceSubject, sourceRFCID, explicitTrash}
            end repeat

            set resultArray to my newArray()
            set succeededCount to 0
            repeat with preparedItem in preparedItems
                set referenceObject to item 1 of preparedItem
                set anAccount to item 2 of preparedItem
                set aMessage to item 3 of preparedItem
                set sourcePath to item 4 of preparedItem
                set localID to item 5 of preparedItem
                set sourceSubject to item 6 of preparedItem
                set sourceRFCID to item 7 of preparedItem
                set explicitTrash to item 8 of preparedItem
                set itemResult to my newDictionary()
                my putValue(itemResult, "source_ref", referenceObject)
                my putValue(itemResult, "mark_read_verified", false)
                my putValue(itemResult, "trash_verified", false)
                try
                    if willRead then
                        set read status of aMessage to true
                        if not (read status of aMessage as boolean) then error "Read status did not persist" number 9317
                        my putValue(itemResult, "mark_read_verified", true)
                    end if
                    if willTrash then
                        if explicitTrash is missing value then
                            delete aMessage
                        else
                            move aMessage to explicitTrash
                        end if
                        set sourceGone to false
                        set trashFound to false
                        repeat with attemptIndex from 1 to attemptLimit
                            delay pollDelay
                            try
                                my findMessage(referenceObject)
                            on error errorMessage number errorNumber
                                if errorNumber is 9106 then
                                    set sourceGone to true
                                else
                                    error errorMessage number errorNumber
                                end if
                            end try
                            try
                                set trashedMessage to my resolveTrashedMessageForAccount(aggregateTrash, anAccount, localID, sourceSubject, sourceRFCID)
                                set trashFound to true
                            on error errorMessage number errorNumber
                                if errorNumber is not 9304 then error errorMessage number errorNumber
                            end try
                            if sourceGone and trashFound then exit repeat
                        end repeat
                        my putValue(itemResult, "removed_from_source", sourceGone)
                        my putValue(itemResult, "trash_present", trashFound)
                        if not sourceGone or not trashFound then error "Trash move could not be verified in both source and destination" number 9318
                        set destinationPath to my mailboxPathForMessage(trashedMessage)
                        set destinationRecord to my messageSummary(trashedMessage, anAccount, destinationPath)
                        set destinationRead to read status of trashedMessage as boolean
                        my putValue(destinationRecord, "read", destinationRead)
                        my putValue(itemResult, "message", destinationRecord)
                        if willRead and not destinationRead then error "Read status did not persist after the Trash move" number 9319
                        my putValue(itemResult, "trash_verified", true)
                    else
                        set sourceRecord to my messageSummary(aMessage, anAccount, sourcePath)
                        my putValue(sourceRecord, "read", read status of aMessage as boolean)
                        my putValue(itemResult, "message", sourceRecord)
                    end if
                    my putValue(itemResult, "ok", true)
                    set succeededCount to succeededCount + 1
                on error errorMessage number errorNumber
                    my putValue(itemResult, "ok", false)
                    my putValue(itemResult, "code", "MAIL_APPLESCRIPT_" & errorNumber)
                    my putValue(itemResult, "error", errorMessage)
                end try
                my addValue(resultArray, itemResult)
            end repeat
            set resultObject to my newDictionary()
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", "act")
            my putValue(resultObject, "complete", succeededCount is referenceCount)
            my putValue(resultObject, "succeeded", succeededCount)
            my putValue(resultObject, "count", referenceCount)
            my putValue(resultObject, "results", resultArray)
            return resultObject
        end tell
    end commandAct


    on commandApplyAction(requestObject)
        set operationName to my requestText(requestObject, "operation", "")
        set referenceObject to my requestValue(requestObject, "message_ref")
        if operationName is "trash" then
            set refsArray to my newArray()
            my addValue(refsArray, referenceObject)
            set actionsArray to my newArray()
            my addValue(actionsArray, "trash")
            set batchRequest to my newDictionary()
            my putValue(batchRequest, "refs", refsArray)
            my putValue(batchRequest, "actions", actionsArray)
            my putValue(batchRequest, "action_verification_attempts", 6)
            my putValue(batchRequest, "poll_interval_seconds", my requestInteger(requestObject, "poll_interval_seconds", 1))
            set batchResult to my commandAct(batchRequest)
            set itemResult to (my requestValue(batchResult, "results"))'s objectAtIndex:0
            my putValue(itemResult, "operation", "trash")
            return itemResult
        end if
        set destinationPath to my pathFromRequest(requestObject, "destination")
        set attachmentID to my requestText(requestObject, "attachment_id", "")
        set outputPath to my requestText(requestObject, "output_path", "")
        set attemptLimit to my requestInteger(requestObject, "send_verification_attempts", 1)
        set pollDelay to my requestInteger(requestObject, "poll_interval_seconds", 1)
        set {anAccount, sourceMailbox, aMessage, sourcePath} to my findMessage(referenceObject)
        tell application "Mail"
            set resultObject to my newDictionary()
            my putValue(resultObject, "ok", true)
            my putValue(resultObject, "operation", operationName)
            if operationName is "mark-read" then
                set read status of aMessage to true
                my putValue(resultObject, "message", my messageDictionary(aMessage, anAccount, sourcePath, "none", false, false))
            else if operationName is "mark-unread" then
                set read status of aMessage to false
                my putValue(resultObject, "message", my messageDictionary(aMessage, anAccount, sourcePath, "none", false, false))
            else if operationName is "flag" then
                set flagged status of aMessage to true
                my putValue(resultObject, "message", my messageDictionary(aMessage, anAccount, sourcePath, "none", false, false))
            else if operationName is "unflag" then
                set flagged status of aMessage to false
                my putValue(resultObject, "message", my messageDictionary(aMessage, anAccount, sourcePath, "none", false, false))
            else if operationName is "move" then
                set destinationMailbox to my resolveMailbox(anAccount, destinationPath)
                move aMessage to destinationMailbox
                set destinationReference to my referenceWithMailboxPath(referenceObject, destinationPath)
                delay pollDelay
                set {movedAccount, movedMailbox, movedMessage, movedPath} to my findMessage(destinationReference)
                my putValue(resultObject, "message", my messageDictionary(movedMessage, movedAccount, movedPath, "none", false, false))
            else if operationName is "save-attachment" then
                if (current application's NSFileManager's defaultManager()'s fileExistsAtPath:outputPath) as boolean then error "Refusing to overwrite attachment output" number 9302
                set anAttachment to my findAttachment(aMessage, attachmentID)
                save anAttachment in POSIX file outputPath
                my putValue(resultObject, "output_path", outputPath)
            else
                error "Unsupported action: " & operationName number 9303
            end if
            return resultObject
        end tell
    end commandApplyAction



end using terms from
