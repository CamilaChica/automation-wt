import React, { useEffect, useState } from 'react';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Clock3,
  Database,
  Gauge,
  Mail,
  Menu,
  Plane,
  ScanLine,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import './LandingPage.css';

const navigation = [
  { label: 'Platform', href: '#platform' },
  { label: 'How it works', href: '#workflow' },
  { label: 'Built with control', href: '#control' },
  { label: 'Outcomes', href: '#outcomes' },
  { label: 'Team portal', href: '/team-portal' },
];

const workflow = [
  {
    number: '01',
    title: 'Read the request',
    description: 'Incoming sales email becomes structured line items: part number, quantity, condition and aircraft context.',
    icon: ScanLine,
  },
  {
    number: '02',
    title: 'Check availability',
    description: 'Inventory and saved supplier offers are searched together, while missing details trigger supplier outreach.',
    icon: Database,
  },
  {
    number: '03',
    title: 'Move the quote forward',
    description: 'A customer-ready response returns in the original thread. Follow-ups and next steps stay connected.',
    icon: Mail,
  },
];

const capabilities = [
  {
    title: 'A faster first response',
    description: 'Routine requests are read, checked and quoted in about one to two minutes—not left waiting in an inbox.',
    icon: Clock3,
    accent: 'cyan',
  },
  {
    title: 'Sourcing that keeps moving',
    description: 'Supplier outreach, discount requests and scheduled customer follow-ups continue across shifts.',
    icon: Gauge,
    accent: 'gold',
  },
  {
    title: 'A record you can follow',
    description: 'Requests, quotes, supplier conversations, purchase orders and audit history stay in one place.',
    icon: Database,
    accent: 'cyan',
  },
];

export const LandingPage: React.FC = () => {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const elements = document.querySelectorAll<HTMLElement>('.wt-reveal');
    const observer = new IntersectionObserver(
      entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.14 },
    );

    elements.forEach(element => observer.observe(element));
    return () => observer.disconnect();
  }, []);

  const closeMenu = () => setMenuOpen(false);

  return (
    <div className="wt-landing">
      <a className="wt-skip-link" href="#main-content">Skip to content</a>
      <header className="wt-header">
        <div className="wt-header-inner">
          <a className="wt-brand" href="#top" aria-label="Winged Tycoons home" onClick={closeMenu}>
            <img src="/branding/WingedTycoons.png" alt="" width="72" height="54" />
            <span className="wt-brand-copy">
              <strong>WINGED TYCOONS</strong>
              <span>AVIATION, IN MOTION</span>
            </span>
          </a>

          <button
            type="button"
            className="wt-menu-toggle"
            aria-label={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
            aria-expanded={menuOpen}
            aria-controls="primary-navigation"
            onClick={() => setMenuOpen(open => !open)}
          >
            {menuOpen ? <X size={21} /> : <Menu size={21} />}
          </button>

          <nav id="primary-navigation" className={`wt-nav${menuOpen ? ' is-open' : ''}`} aria-label="Main navigation">
            {navigation.map(item => (
              <a key={item.href} href={item.href} onClick={closeMenu}>{item.label}</a>
            ))}
          </nav>

          <a className="wt-login" href="/customer-portal">
            Login <ArrowUpRight size={15} aria-hidden="true" />
          </a>
        </div>
      </header>

      <main id="main-content">
        <section className="wt-hero" id="top" aria-labelledby="hero-heading">
          <div className="wt-hero-grid">
            <div className="wt-hero-copy">
              <div className="wt-eyebrow"><span className="wt-live-dot" /> THE AUTONOMOUS PARTS DESK</div>
              <h1 id="hero-heading">
                Keep aircraft moving.
                <span> Let sourcing move at speed.</span>
              </h1>
              <p className="wt-hero-lede">
                AOG and MRO parts sourcing, orchestrated. Winged Tycoons reads the request,
                checks availability and gets a quote moving—while your team stays in control
                of the decisions that matter.
              </p>
              <div className="wt-hero-actions">
                <a className="wt-button wt-button-primary" href="mailto:sales@wingedtycoons.com?subject=Winged%20Tycoons%20demo%20request">
                  See it on a real RFQ <ArrowRight size={17} aria-hidden="true" />
                </a>
                <a className="wt-text-link" href="#workflow">
                  Explore the workflow <ArrowDown size={15} aria-hidden="true" />
                </a>
              </div>
              <div className="wt-hero-proof">
                <span><Check size={15} aria-hidden="true" /> Live in production</span>
                <span><Check size={15} aria-hidden="true" /> Human-led exceptions</span>
                <span><Check size={15} aria-hidden="true" /> Full activity record</span>
              </div>
            </div>

            <div className="wt-hero-visual" aria-label="Aircraft engine maintenance and live parts sourcing view">
              <div className="wt-hero-photo" role="img" aria-label="Aircraft engine in a maintenance hangar" />
              <div className="wt-photo-shade" />
              <div className="wt-visual-coordinate">AOG RESPONSE SYSTEM <span> / 24·7</span></div>
              <div className="wt-rfq-card">
                <div className="wt-rfq-topline">
                  <span className="wt-rfq-status"><i /> REQUEST IN MOTION</span>
                  <span className="wt-rfq-id">RFQ—2048</span>
                </div>
                <div className="wt-rfq-part">
                  <div className="wt-part-glyph"><Plane size={20} /></div>
                  <div><span>PART NUMBER</span><strong>65C26714-2</strong></div>
                  <span className="wt-part-count">× 02</span>
                </div>
                <div className="wt-rfq-rule" />
                <div className="wt-rfq-steps">
                  <span className="done"><i><Check size={10} /></i> Intake</span>
                  <span className="done"><i><Check size={10} /></i> Stock check</span>
                  <span className="active"><i><Sparkles size={10} /></i> Supplier match</span>
                </div>
                <div className="wt-rfq-bottom">
                  <span><span className="wt-live-dot" /> AUTOMATION ACTIVE</span>
                  <span>01:24 <small>elapsed</small></span>
                </div>
              </div>
              <div className="wt-visual-side-note">PRECISION IN EVERY HANDOFF <span>WT / 01</span></div>
            </div>
          </div>
          <a className="wt-scroll-cue" href="#platform" aria-label="Scroll to the platform section">
            <span /> SCROLL TO EXPLORE
          </a>
          <div className="wt-hero-index" aria-hidden="true">01 — 04</div>
        </section>

        <section className="wt-signal-strip" aria-label="Platform operating characteristics">
          <div className="wt-signal-inner">
            <div><span className="wt-strip-kicker">BUILT FOR</span><strong>AOG + MRO OPERATIONS</strong></div>
            <div><span className="wt-strip-kicker">FIRST RESPONSE</span><strong>ABOUT 1–2 MINUTES</strong></div>
            <div><span className="wt-strip-kicker">MAILBOX CHECKS</span><strong>EVERY 60 SECONDS</strong></div>
            <div><span className="wt-strip-kicker">OPERATING MODEL</span><strong>AUTONOMOUS, WITH GUARDRAILS</strong></div>
          </div>
        </section>

        <section className="wt-section wt-platform" id="platform" aria-labelledby="platform-heading">
          <div className="wt-section-heading wt-reveal">
            <div>
              <span className="wt-eyebrow wt-eyebrow-dark">01 / THE PLATFORM</span>
              <h2 id="platform-heading">The sourcing desk,<br /><em>in a higher gear.</em></h2>
            </div>
            <p>Free-text requests. Scattered supplier replies. Follow-ups that depend on memory. The familiar workflow is built for a slower era.</p>
          </div>
          <div className="wt-capability-grid">
            {capabilities.map((capability, index) => {
              const Icon = capability.icon;
              return (
                <article className={`wt-capability wt-reveal wt-accent-${capability.accent}`} key={capability.title} style={{ transitionDelay: `${index * 90}ms` }}>
                  <div className="wt-capability-icon"><Icon size={20} strokeWidth={1.7} /></div>
                  <span className="wt-card-index">0{index + 1}</span>
                  <h3>{capability.title}</h3>
                  <p>{capability.description}</p>
                  <div className="wt-card-line" />
                </article>
              );
            })}
          </div>
          <div className="wt-platform-note wt-reveal">
            <div className="wt-note-symbol"><Sparkles size={18} /></div>
            <p><strong>Less inbox choreography. More judgment where it counts.</strong> Routine work moves in the background, freeing your people to focus on exceptions, customers and supplier relationships.</p>
            <a href="#control" aria-label="Explore human oversight"><ChevronRight size={19} /></a>
          </div>
        </section>

        <section className="wt-workflow" id="workflow" aria-labelledby="workflow-heading">
          <div className="wt-workflow-inner">
            <div className="wt-workflow-intro wt-reveal">
              <span className="wt-eyebrow"><span className="wt-eyebrow-number">02</span> / THE FLIGHT PATH</span>
              <h2 id="workflow-heading">From request<br />to response.<br /><em>Without the runway wait.</em></h2>
              <p>One connected loop from the customer’s first email to a quote, follow-through and a recorded next step.</p>
              <a className="wt-button wt-button-outline" href="mailto:sales@wingedtycoons.com?subject=Winged%20Tycoons%20demo%20request">
                Walk through a request <ArrowRight size={16} />
              </a>
            </div>
            <div className="wt-workflow-list">
              {workflow.map((step, index) => {
                const Icon = step.icon;
                return (
                  <article className="wt-workflow-step wt-reveal" key={step.number} style={{ transitionDelay: `${index * 110}ms` }}>
                    <div className="wt-step-rail"><span>{step.number}</span><i /></div>
                    <div className="wt-step-content">
                      <div className="wt-step-icon"><Icon size={18} /></div>
                      <div><h3>{step.title}</h3><p>{step.description}</p></div>
                    </div>
                    <ArrowUpRight className="wt-step-arrow" size={18} aria-hidden="true" />
                  </article>
                );
              })}
              <div className="wt-workflow-footnote"><span /> The mailbox is monitored continuously; polling cadence can be adjusted to your operation.</div>
            </div>
          </div>
        </section>

        <section className="wt-control wt-section" id="control" aria-labelledby="control-heading">
          <div className="wt-control-visual wt-reveal">
            <div className="wt-control-grid" aria-hidden="true" />
            <div className="wt-control-orbit wt-orbit-one" aria-hidden="true" />
            <div className="wt-control-orbit wt-orbit-two" aria-hidden="true" />
            <div className="wt-control-center"><ShieldCheck size={35} strokeWidth={1.3} /></div>
            <div className="wt-control-tag wt-tag-top"><span>01</span> ROUTINE RFQ <i>· AUTOMATED</i></div>
            <div className="wt-control-tag wt-tag-right"><span>02</span> AOG / UNCLEAR <i>· REVIEW</i></div>
            <div className="wt-control-tag wt-tag-bottom"><span>03</span> PURCHASE ORDER <i>· APPROVAL</i></div>
            <div className="wt-control-tag wt-tag-left"><span>04</span> AUDIT TRAIL <i>· RECORDED</i></div>
          </div>
          <div className="wt-control-copy wt-reveal">
            <span className="wt-eyebrow wt-eyebrow-dark">03 / HUMAN OVERSIGHT</span>
            <h2 id="control-heading">Autonomous<br />by design.<br /><em>Accountable by default.</em></h2>
            <p>Speed is only valuable when it is safe. Winged Tycoons moves routine work forward and routes exceptions to your team.</p>
            <ul>
              <li><Check size={16} /> Urgent and AOG requests are reviewed by a person.</li>
              <li><Check size={16} /> Ambiguous requests are escalated—not guessed.</li>
              <li><Check size={16} /> Purchase orders remain subject to internal approval.</li>
              <li><Check size={16} /> Supplier price floors and negotiation limits stay in force.</li>
            </ul>
            <a className="wt-inline-link" href="#outcomes">Explore the operational outcomes <ArrowRight size={15} /></a>
          </div>
        </section>

        <section className="wt-outcomes" id="outcomes" aria-labelledby="outcomes-heading">
          <div className="wt-outcomes-inner wt-reveal">
            <div className="wt-outcomes-heading">
              <span className="wt-eyebrow"><span className="wt-eyebrow-number">04</span> / THE ADVANTAGE</span>
              <h2 id="outcomes-heading">Make every minute<br /><em>work harder.</em></h2>
            </div>
            <div className="wt-outcome-list">
              <div><span>01</span><p><strong>Respond sooner.</strong> Get a credible quote in front of customers while the request is still active.</p></div>
              <div><span>02</span><p><strong>Protect margin.</strong> Apply consistent supplier negotiation rules with a defined price floor.</p></div>
              <div><span>03</span><p><strong>Scale the desk.</strong> Handle more routine work without adding the same amount of admin overhead.</p></div>
              <div><span>04</span><p><strong>Keep the thread.</strong> Track decisions, messages and next steps in a searchable activity record.</p></div>
            </div>
          </div>
          <div className="wt-outcomes-caption"><span>WT—SYSTEMS / OPERATIONS</span><span>BUILT TO KEEP THE WORLD MOVING</span></div>
        </section>

        <section className="wt-final-cta" aria-labelledby="cta-heading">
          <div className="wt-cta-glow" aria-hidden="true" />
          <div className="wt-cta-inner wt-reveal">
            <span className="wt-eyebrow"><span className="wt-live-dot" /> THE NEXT MOVE IS YOURS</span>
            <h2 id="cta-heading">See it work on<br /><em>a real request.</em></h2>
            <p>Bring a recent RFQ or a typical AOG scenario. We’ll show how the system reads it, sources it and responds—then map the right guardrails for your team.</p>
            <div className="wt-cta-actions">
              <a className="wt-button wt-button-primary" href="mailto:sales@wingedtycoons.com?subject=Winged%20Tycoons%20demo%20request">
                Request a live demonstration <ArrowRight size={17} />
              </a>
              <span>No obligation. A working session tailored to your operation.</span>
            </div>
          </div>
          <div className="wt-cta-index">PRECISION. PACE. PROGRESS.</div>
        </section>
      </main>

      <footer className="wt-footer">
        <a className="wt-brand" href="#top" aria-label="Winged Tycoons home">
          <img src="/branding/WingedTycoons.png" alt="" width="60" height="46" />
          <span className="wt-brand-copy"><strong>WINGED TYCOONS</strong><span>AVIATION, IN MOTION</span></span>
        </a>
        <p>Autonomous parts sourcing for AOG and MRO.</p>
        <a className="wt-footer-contact" href="mailto:sales@wingedtycoons.com">CONTACT <ArrowUpRight size={13} /></a>
        <span className="wt-copyright">© {new Date().getFullYear()} WINGED TYCOONS</span>
      </footer>
    </div>
  );
};

export default LandingPage;
