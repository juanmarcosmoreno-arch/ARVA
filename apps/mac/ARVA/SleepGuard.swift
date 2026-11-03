import Foundation
import IOKit.pwr_mgt

/// Keeps the Mac from going to sleep on its own while ARVA has analyses running or waiting, so a long batch is not
/// paused overnight. It holds one power assertion of type PreventUserIdleSystemSleep (IOKit's IOPMLib.h:
/// kIOPMAssertionTypePreventUserIdleSystemSleep, which names kIOPMAssertPreventUserIdleSystemSleep), created with
/// IOPMAssertionCreateWithName and released with IOPMAssertionRelease. IOPMLib.h: it "will prevent the system from
/// sleeping due to a period of idle user activity"; "The display may dim and idle sleep ... The system may still
/// sleep for lid close, Apple menu, low battery, or other sleep reasons." No special privileges are needed. The
/// assertion also ends when the app's process ends.
///
/// The count of analyses comes from GET /api/v1/dashboard (`jobs_running`: running plus pending jobs), asked every
/// `pollInterval` seconds. The assertion is released after `idlePollsToRelease` answers of 0 in a row (a batch
/// queues its next job as the previous one ends, so one 0 between two jobs is not the end), after
/// `unknownPollsToRelease` polls in a row without an answer, when ARVA stops, and when the app quits.
final class SleepGuard {
    /// What creates and releases the assertion: the system's power management, or a stand-in in the self-test.
    struct Backend {
        let create: (String) -> IOPMAssertionID?
        let release: (IOPMAssertionID) -> Bool
    }

    static let system = Backend(
        create: { name in
            var id = IOPMAssertionID(0)
            let result = IOPMAssertionCreateWithName(kIOPMAssertPreventUserIdleSystemSleep as CFString,
                                                     IOPMAssertionLevel(kIOPMAssertionLevelOn), name as CFString, &id)
            return result == kIOReturnSuccess ? id : nil
        },
        release: { id in IOPMAssertionRelease(id) == kIOReturnSuccess }
    )

    static let pollInterval: TimeInterval = 60
    static let idlePollsToRelease = 2
    static let unknownPollsToRelease = 5
    /// The assertion's name, as `pmset -g assertions` lists it (IOPMLib.h: no longer than 128 characters).
    static let assertionName = "ARVA: analyses running or waiting"

    /// The status line shown while the assertion is held (app menu and the window's subtitle).
    static var statusText: String {
        L("The Mac will not sleep while analyses are running", "La Mac no se suspenderá mientras haya análisis en curso")
    }

    private let backend: Backend
    private(set) var assertion: IOPMAssertionID?
    private var idlePolls = 0
    private var unknownPolls = 0
    /// Called with true when the assertion is taken and false when it is released.
    var onChange: ((Bool) -> Void)?

    init(backend: Backend = SleepGuard.system) {
        self.backend = backend
    }

    var isActive: Bool { assertion != nil }

    /// One answer of the dashboard: the analyses running or waiting, or nil when ARVA did not answer.
    func update(activeJobs: Int?) {
        switch activeJobs {
        case .some(let count) where count > 0:
            idlePolls = 0
            unknownPolls = 0
            if assertion == nil, let id = backend.create(SleepGuard.assertionName) {
                assertion = id
                onChange?(true)
            }
        case .some:
            unknownPolls = 0
            idlePolls += 1
            if idlePolls >= SleepGuard.idlePollsToRelease { release() }
        case .none:
            unknownPolls += 1
            if unknownPolls >= SleepGuard.unknownPollsToRelease { release() }
        }
    }

    /// Lets the Mac sleep again (nothing to do when no assertion is held).
    func release() {
        idlePolls = 0
        unknownPolls = 0
        guard let id = assertion else { return }
        _ = backend.release(id)
        assertion = nil
        onChange?(false)
    }
}
